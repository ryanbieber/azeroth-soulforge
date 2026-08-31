/*
 * Copyright (C) 2026 Azeroth Soulforge contributors
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "Config.h"
#include "Channel.h"
#include "ChannelMgr.h"
#include "Chat.h"
#include "CommandScript.h"
#include "Group.h"
#include "Guild.h"
#include "GuildMgr.h"
#include "Log.h"
#include "ObjectAccessor.h"
#include "Player.h"
#include "PlayerScript.h"
#include "Playerbots.h"
#include "ScriptMgr.h"
#include "WorldScript.h"

#include <boost/asio.hpp>
#include <boost/uuid/random_generator.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <openssl/hmac.h>

#include <atomic>
#include <chrono>
#include <cctype>
#include <ctime>
#include <deque>
#include <iomanip>
#include <iterator>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

namespace SoulBridge
{
struct Event
{
    std::string Payload;
};

struct Reply
{
    std::string ReplyId;
    uint32 BotGuid = 0;
    uint32 RecipientGuid = 0;
    std::string Channel;
    std::string ChannelName;
    std::string Text;
};

struct RosterReply
{
    uint32 RecipientGuid = 0;
    bool Available = false;
    std::vector<std::pair<std::string, std::string>> Companions;
};

std::string JsonEscape(std::string const& value)
{
    std::ostringstream output;
    for (unsigned char character : value)
    {
        switch (character)
        {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\b': output << "\\b"; break;
            case '\f': output << "\\f"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (character < 0x20)
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(character);
                else
                    output << character;
        }
    }
    return output.str();
}

std::string Lower(std::string value)
{
    for (char& character : value)
        character = static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
    return value;
}

bool Mentions(Player const* bot, std::string const& message)
{
    return bot && Lower(message).find(Lower(bot->GetName())) != std::string::npos;
}

Player* MentionedControlledBot(Player* player, std::string const& message)
{
    PlayerbotMgr* manager = player ? GET_PLAYERBOT_MGR(player) : nullptr;
    if (!manager)
        return nullptr;
    for (auto iterator = manager->GetPlayerBotsBegin(); iterator != manager->GetPlayerBotsEnd(); ++iterator)
    {
        Player* bot = iterator->second;
        if (bot && GET_PLAYERBOT_AI(bot) && Mentions(bot, message))
            return bot;
    }
    return nullptr;
}

std::optional<std::string> JsonStringField(std::string const& document, std::string const& key, std::size_t start)
{
    std::string marker = "\"" + key + "\":\"";
    std::size_t cursor = document.find(marker, start);
    if (cursor == std::string::npos)
        return std::nullopt;
    cursor += marker.size();
    std::string value;
    bool escaped = false;
    for (; cursor < document.size(); ++cursor)
    {
        char character = document[cursor];
        if (escaped)
        {
            switch (character)
            {
                case 'n': value += '\n'; break;
                case 'r': value += '\r'; break;
                case 't': value += '\t'; break;
                case 'b': value += '\b'; break;
                case 'f': value += '\f'; break;
                default: value += character; break;
            }
            escaped = false;
        }
        else if (character == '\\')
            escaped = true;
        else if (character == '"')
            return value;
        else
            value += character;
    }
    return std::nullopt;
}

class Bridge
{
public:
    static Bridge& Instance()
    {
        static Bridge instance;
        return instance;
    }

    void Configure()
    {
        if (_running)
            return;
        _enabled = sConfigMgr->GetOption<bool>("SoulBridge.Enabled", true);
        _host = sConfigMgr->GetOption<std::string>("SoulBridge.ServiceHost", "soul-service");
        _port = sConfigMgr->GetOption<uint16>("SoulBridge.ServicePort", 8765);
        _realmId = sConfigMgr->GetOption<std::string>("SoulBridge.RealmId", "azeroth-soulforge");
        _consumerId = sConfigMgr->GetOption<std::string>("SoulBridge.ConsumerId", "worldserver-1");
        _secret = sConfigMgr->GetOption<std::string>("SoulBridge.SharedSecret", "");
        _capacity = sConfigMgr->GetOption<uint32>("SoulBridge.QueueCapacity", 2048);
        _pollInterval = sConfigMgr->GetOption<uint32>("SoulBridge.PollIntervalMs", 500);
        _timeout = sConfigMgr->GetOption<uint32>("SoulBridge.RequestTimeoutSeconds", 5);
    }

    void Start()
    {
        if (!_enabled)
        {
            LOG_INFO("module.soulbridge", "Soulbridge is disabled");
            return;
        }
        if (_secret.empty())
        {
            LOG_ERROR("module.soulbridge", "SoulBridge.SharedSecret is empty; bridge will not start");
            return;
        }
        _running = true;
        _worker = std::thread([this]() { WorkerLoop(); });
        LOG_INFO("module.soulbridge", "Soulbridge worker started for {}:{}", _host, _port);
    }

    void Stop()
    {
        _running = false;
        if (_worker.joinable())
            _worker.join();
    }

    void Enqueue(Player const* player, Player const* bot, uint32 type, std::string const& message,
        std::string const& channelName = "")
    {
        if (!_running || !player || !bot || message.empty())
            return;

        std::string eventId = boost::uuids::to_string(boost::uuids::random_generator()());
        std::string traceId = boost::uuids::to_string(boost::uuids::random_generator()());
        std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        std::tm timestamp{};
        gmtime_r(&now, &timestamp);
        std::ostringstream occurredAt;
        occurredAt << std::put_time(&timestamp, "%Y-%m-%dT%H:%M:%SZ");

        std::string channel = "party";
        if (type == CHAT_MSG_WHISPER)
            channel = "whisper";
        else if (type == CHAT_MSG_SAY)
            channel = "say";
        else if (type == CHAT_MSG_GUILD || type == CHAT_MSG_OFFICER)
            channel = "guild";
        else if (type == CHAT_MSG_RAID || type == CHAT_MSG_RAID_LEADER || type == CHAT_MSG_RAID_WARNING)
            channel = "raid";
        else if (type == CHAT_MSG_CHANNEL)
            channel = "channel";
        std::ostringstream payload;
        payload << "{\"schema_version\":\"1.0\",\"event_id\":\"" << eventId
                << "\",\"realm_id\":\"" << JsonEscape(_realmId)
                << "\",\"event_type\":\"chat." << channel
                << "\",\"occurred_at\":\"" << occurredAt.str()
                << "\",\"actor\":{\"guid\":\"" << player->GetGUID().GetCounter()
                << "\",\"kind\":\"human\",\"name\":\"" << JsonEscape(player->GetName())
                << "\"},\"participants\":[{\"guid\":\"" << bot->GetGUID().GetCounter()
                << "\",\"kind\":\"soul\",\"name\":\"" << JsonEscape(bot->GetName())
                << "\"}],\"channel\":\"" << channel << "\",\"text\":\"" << JsonEscape(message)
                << "\",\"context\":{\"target_bot_guid\":\"" << bot->GetGUID().GetCounter()
                << "\",\"target_bot_name\":\"" << JsonEscape(bot->GetName())
                << "\"";
        if (!channelName.empty())
            payload << ",\"channel_name\":\"" << JsonEscape(channelName) << "\"";
        payload << "},\"trace\":{\"trace_id\":\"" << traceId
                << "\",\"origin\":\"human\",\"hop_count\":0}}";

        std::lock_guard<std::mutex> lock(_eventMutex);
        if (_events.size() >= _capacity)
        {
            ++_dropped;
            return;
        }
        _events.push_back({ payload.str() });
    }

    void RequestRoster(Player const* player)
    {
        if (!_running || !player)
            return;
        std::lock_guard<std::mutex> lock(_rosterMutex);
        if (_rosterRequests.size() < 32)
            _rosterRequests.push_back(player->GetGUID().GetCounter());
    }

    void DeliverReplies()
    {
        DeliverRosterReplies();
        for (uint32 delivered = 0; delivered < 5; ++delivered)
        {
            std::optional<Reply> reply;
            {
                std::lock_guard<std::mutex> lock(_replyMutex);
                if (_replies.empty())
                    return;
                reply = std::move(_replies.front());
                _replies.pop_front();
            }

            Player* bot = ObjectAccessor::FindPlayerByLowGUID(reply->BotGuid);
            Player* recipient = ObjectAccessor::FindPlayerByLowGUID(reply->RecipientGuid);
            if (!bot || !recipient || !GET_PLAYERBOT_AI(bot))
            {
                std::lock_guard<std::mutex> lock(_replyMutex);
                _pendingReplyIds.erase(reply->ReplyId);
                continue;
            }
            bool sent = false;
            if (reply->Channel == "whisper")
            {
                bot->Whisper(reply->Text, LANG_UNIVERSAL, recipient);
                sent = true;
            }
            else if (reply->Channel == "say")
            {
                bot->Say(reply->Text, LANG_UNIVERSAL);
                sent = true;
            }
            else if (reply->Channel == "party" || reply->Channel == "raid")
            {
                if (Group* group = bot->GetGroup())
                {
                    ChatMsg type = reply->Channel == "raid" ? CHAT_MSG_RAID : CHAT_MSG_PARTY;
                    WorldPacket data;
                    ChatHandler::BuildChatPacket(data, type, LANG_UNIVERSAL, bot, nullptr, reply->Text);
                    if (type == CHAT_MSG_RAID)
                        group->BroadcastPacket(&data, false);
                    else
                        group->BroadcastPacket(&data, false, group->GetMemberGroup(bot->GetGUID()));
                    sent = true;
                }
            }
            else if (reply->Channel == "guild")
            {
                if (Guild* guild = sGuildMgr->GetGuildById(bot->GetGuildId()))
                {
                    guild->BroadcastToGuild(bot->GetSession(), false, reply->Text, LANG_UNIVERSAL);
                    sent = true;
                }
            }
            else if (reply->Channel == "channel" && !reply->ChannelName.empty())
            {
                if (ChannelMgr* manager = ChannelMgr::forTeam(bot->GetTeamId()))
                    if (Channel* channel = manager->GetChannel(reply->ChannelName, bot))
                    {
                        channel->Say(bot->GetGUID(), reply->Text, LANG_UNIVERSAL);
                        sent = true;
                    }
            }
            if (!sent)
            {
                std::lock_guard<std::mutex> lock(_replyMutex);
                _pendingReplyIds.erase(reply->ReplyId);
                continue;
            }
            {
                std::lock_guard<std::mutex> lock(_replyMutex);
                _acknowledgements.push_back(reply->ReplyId);
            }
        }
    }

private:
    struct HttpResponse
    {
        int Status = 0;
        std::string Body;
    };

    std::string Sign(std::string const& method, std::string const& target, std::string const& timestamp,
        std::string const& nonce, std::string const& body) const
    {
        std::string canonical = method + "\n" + target + "\n" + timestamp + "\n" + nonce + "\n" + body;
        unsigned int length = 0;
        unsigned char digest[EVP_MAX_MD_SIZE];
        HMAC(EVP_sha256(), _secret.data(), static_cast<int>(_secret.size()),
            reinterpret_cast<unsigned char const*>(canonical.data()), canonical.size(), digest, &length);
        std::ostringstream output;
        for (unsigned int index = 0; index < length; ++index)
            output << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(digest[index]);
        return output.str();
    }

    HttpResponse Request(std::string const& method, std::string const& target, std::string const& body)
    {
        auto now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        std::string timestamp = std::to_string(now);
        std::string nonce = boost::uuids::to_string(boost::uuids::random_generator()());

        boost::asio::ip::tcp::iostream stream;
        stream.expires_after(std::chrono::seconds(_timeout));
        stream.connect(_host, std::to_string(_port));
        if (!stream)
            return {};

        stream << method << " " << target << " HTTP/1.1\r\n"
               << "Host: " << _host << "\r\n"
               << "Content-Type: application/json\r\n"
               << "Content-Length: " << body.size() << "\r\n"
               << "X-Soulforge-Timestamp: " << timestamp << "\r\n"
               << "X-Soulforge-Nonce: " << nonce << "\r\n"
               << "X-Soulforge-Signature: " << Sign(method, target, timestamp, nonce, body) << "\r\n"
               << "Connection: close\r\n\r\n" << body << std::flush;

        std::string version;
        HttpResponse response;
        stream >> version >> response.Status;
        std::string line;
        std::getline(stream, line);
        while (std::getline(stream, line) && line != "\r") { }
        response.Body.assign(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
        return response;
    }

    void WorkerLoop()
    {
        while (_running)
        {
            std::optional<Event> event;
            {
                std::lock_guard<std::mutex> lock(_eventMutex);
                if (!_events.empty())
                {
                    event = std::move(_events.front());
                    _events.pop_front();
                }
            }
            if (event)
            {
                HttpResponse response = Request("POST", "/v1/events", event->Payload);
                if (response.Status != 202)
                    LOG_DEBUG("module.soulbridge", "Event delivery returned HTTP {}", response.Status);
            }

            std::optional<uint32> rosterRecipient;
            {
                std::lock_guard<std::mutex> lock(_rosterMutex);
                if (!_rosterRequests.empty())
                {
                    rosterRecipient = _rosterRequests.front();
                    _rosterRequests.pop_front();
                }
            }
            if (rosterRecipient)
                FetchRoster(*rosterRecipient);

            AcknowledgeReplies();
            PollReplies();
            std::this_thread::sleep_for(std::chrono::milliseconds(_pollInterval));
        }
    }

    void FetchRoster(uint32 recipientGuid)
    {
        std::string target = "/v1/companion-roster?realm_id=" + _realmId;
        HttpResponse response = Request("GET", target, "");
        RosterReply roster;
        roster.RecipientGuid = recipientGuid;
        roster.Available = response.Status == 200;
        if (roster.Available)
        {
            std::size_t cursor = 0;
            while ((cursor = response.Body.find("\"name\":", cursor)) != std::string::npos)
            {
                auto name = JsonStringField(response.Body, "name", cursor);
                auto role = JsonStringField(response.Body, "role", cursor);
                if (!name || !role)
                    break;
                roster.Companions.emplace_back(*name, *role);
                cursor += 7;
            }
        }
        std::lock_guard<std::mutex> lock(_rosterMutex);
        _rosterReplies.push_back(std::move(roster));
    }

    void DeliverRosterReplies()
    {
        for (uint32 delivered = 0; delivered < 5; ++delivered)
        {
            std::optional<RosterReply> roster;
            {
                std::lock_guard<std::mutex> lock(_rosterMutex);
                if (_rosterReplies.empty())
                    return;
                roster = std::move(_rosterReplies.front());
                _rosterReplies.pop_front();
            }
            Player* recipient = ObjectAccessor::FindPlayerByLowGUID(roster->RecipientGuid);
            if (!recipient)
                continue;
            ChatHandler handler(recipient->GetSession());
            if (!roster->Available)
            {
                handler.SendSysMessage("SOULFORGE_ROSTER:ERROR");
                continue;
            }
            handler.SendSysMessage("SOULFORGE_ROSTER:BEGIN");
            for (auto const& [name, role] : roster->Companions)
                handler.SendSysMessage("SOULFORGE_ROSTER:" + name + ":" + role);
            handler.SendSysMessage("SOULFORGE_ROSTER:END");
        }
    }

    void PollReplies()
    {
        std::string target = "/v1/outbox?realm_id=" + _realmId + "&consumer_id=" + _consumerId + "&limit=20";
        HttpResponse response = Request("GET", target, "");
        if (response.Status != 200 || response.Body.empty())
            return;

        std::size_t cursor = 0;
        while ((cursor = response.Body.find("\"reply_id\":", cursor)) != std::string::npos)
        {
            auto replyId = JsonStringField(response.Body, "reply_id", cursor);
            auto botGuid = JsonStringField(response.Body, "bot_guid", cursor);
            auto recipientGuid = JsonStringField(response.Body, "recipient_guid", cursor);
            auto channel = JsonStringField(response.Body, "channel", cursor);
            auto channelName = JsonStringField(response.Body, "channel_name", cursor);
            auto text = JsonStringField(response.Body, "text", cursor);
            if (!replyId || !botGuid || !recipientGuid || !channel || !text)
            {
                LOG_WARN("module.soulbridge", "Invalid outbox response near byte {}", cursor);
                return;
            }
            Reply reply;
            reply.ReplyId = *replyId;
            reply.Channel = *channel;
            reply.ChannelName = channelName.value_or("");
            try
            {
                reply.BotGuid = static_cast<uint32>(std::stoul(*botGuid));
                reply.RecipientGuid = static_cast<uint32>(std::stoul(*recipientGuid));
            }
            catch (std::exception const&)
            {
                cursor += 11;
                continue;
            }
            reply.Text = *text;
            {
                std::lock_guard<std::mutex> lock(_replyMutex);
                if (!_pendingReplyIds.insert(reply.ReplyId).second)
                {
                    cursor += 11;
                    continue;
                }
                _replies.push_back(std::move(reply));
            }
            cursor += 11;
        }
    }

    void AcknowledgeReplies()
    {
        std::deque<std::string> acknowledgements;
        {
            std::lock_guard<std::mutex> lock(_replyMutex);
            acknowledgements.swap(_acknowledgements);
        }
        for (std::string const& replyId : acknowledgements)
        {
            HttpResponse response = Request("POST", "/v1/outbox/" + replyId + "/ack",
                "{\"consumer_id\":\"" + JsonEscape(_consumerId) + "\",\"delivered_at\":\"" + UtcNow() + "\"}");
            std::lock_guard<std::mutex> lock(_replyMutex);
            if (response.Status == 204 || response.Status == 404)
                _pendingReplyIds.erase(replyId);
            else
                _acknowledgements.push_back(replyId);
        }
    }

    static std::string UtcNow()
    {
        std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        std::tm timestamp{};
        gmtime_r(&now, &timestamp);
        std::ostringstream output;
        output << std::put_time(&timestamp, "%Y-%m-%dT%H:%M:%SZ");
        return output.str();
    }

    std::atomic<bool> _running = false;
    bool _enabled = true;
    std::string _host;
    uint16 _port = 8765;
    std::string _realmId;
    std::string _consumerId;
    std::string _secret;
    uint32 _capacity = 2048;
    uint32 _pollInterval = 500;
    uint32 _timeout = 5;
    std::atomic<uint64> _dropped = 0;
    std::thread _worker;
    std::mutex _eventMutex;
    std::deque<Event> _events;
    std::mutex _replyMutex;
    std::deque<Reply> _replies;
    std::deque<std::string> _acknowledgements;
    std::unordered_set<std::string> _pendingReplyIds;
    std::mutex _rosterMutex;
    std::deque<uint32> _rosterRequests;
    std::deque<RosterReply> _rosterReplies;
};

class SoulBridgeCommandScript : public CommandScript
{
public:
    SoulBridgeCommandScript() : CommandScript("SoulBridgeCommandScript") { }

    Acore::ChatCommands::ChatCommandTable GetCommands() const override
    {
        using namespace Acore::ChatCommands;
        static ChatCommandTable soulforgeCommands =
        {
            { "roster", HandleRosterCommand, SEC_PLAYER, Console::No }
        };
        static ChatCommandTable commands =
        {
            { "soulforge", soulforgeCommands }
        };
        return commands;
    }

    static bool HandleRosterCommand(ChatHandler* handler)
    {
        Player* player = handler->GetPlayer();
        if (!player)
            return false;
        Bridge::Instance().RequestRoster(player);
        return true;
    }
};

class SoulBridgePlayerScript : public PlayerScript
{
public:
    SoulBridgePlayerScript() : PlayerScript("SoulBridgePlayerScript", {
        PLAYERHOOK_CAN_PLAYER_USE_CHAT,
        PLAYERHOOK_CAN_PLAYER_USE_PRIVATE_CHAT,
        PLAYERHOOK_CAN_PLAYER_USE_GROUP_CHAT,
        PLAYERHOOK_CAN_PLAYER_USE_GUILD_CHAT,
        PLAYERHOOK_CAN_PLAYER_USE_CHANNEL_CHAT
    }) { }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32, std::string& message) override
    {
        if (type == CHAT_MSG_SAY && player && !GET_PLAYERBOT_AI(player))
            if (Player* bot = MentionedControlledBot(player, message))
                Bridge::Instance().Enqueue(player, bot, type, message);
        return true;
    }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32, std::string& message, Player* receiver) override
    {
        if (type == CHAT_MSG_WHISPER && player && !GET_PLAYERBOT_AI(player) && receiver && GET_PLAYERBOT_AI(receiver))
            Bridge::Instance().Enqueue(player, receiver, type, message);
        return true;
    }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32, std::string& message, Group* group) override
    {
        if (!player || GET_PLAYERBOT_AI(player) || !group)
            return true;
        for (GroupReference* reference = group->GetFirstMember(); reference; reference = reference->next())
        {
            Player* member = reference->GetSource();
            if (member && GET_PLAYERBOT_AI(member) && Mentions(member, message))
            {
                Bridge::Instance().Enqueue(player, member, type, message);
                break;
            }
        }
        return true;
    }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32, std::string& message, Guild*) override
    {
        if (!player || GET_PLAYERBOT_AI(player) || type != CHAT_MSG_GUILD)
            return true;
        PlayerbotMgr* manager = GET_PLAYERBOT_MGR(player);
        if (!manager)
            return true;
        for (auto iterator = manager->GetPlayerBotsBegin(); iterator != manager->GetPlayerBotsEnd(); ++iterator)
        {
            Player* bot = iterator->second;
            if (bot && bot->GetGuildId() == player->GetGuildId() && Mentions(bot, message))
            {
                Bridge::Instance().Enqueue(player, bot, type, message);
                break;
            }
        }
        return true;
    }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32, std::string& message, Channel* channel) override
    {
        if (type == CHAT_MSG_CHANNEL && player && !GET_PLAYERBOT_AI(player) && channel)
            if (Player* bot = MentionedControlledBot(player, message))
                Bridge::Instance().Enqueue(player, bot, type, message, channel->GetName());
        return true;
    }
};

class SoulBridgeWorldScript : public WorldScript
{
public:
    SoulBridgeWorldScript() : WorldScript("SoulBridgeWorldScript", {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD, WORLDHOOK_ON_STARTUP, WORLDHOOK_ON_UPDATE, WORLDHOOK_ON_SHUTDOWN
    }) { }

    void OnAfterConfigLoad(bool) override { Bridge::Instance().Configure(); }
    void OnStartup() override { Bridge::Instance().Start(); }
    void OnUpdate(uint32) override { Bridge::Instance().DeliverReplies(); }
    void OnShutdown() override { Bridge::Instance().Stop(); }
};
}

void Addmod_soulbridgeScripts()
{
    new SoulBridge::SoulBridgeCommandScript();
    new SoulBridge::SoulBridgePlayerScript();
    new SoulBridge::SoulBridgeWorldScript();
}
