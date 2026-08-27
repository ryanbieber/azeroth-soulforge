PartyCommander = PartyCommander or {}
local commander = PartyCommander

BINDING_HEADER_PARTYCOMMANDER = "Party Commander"
BINDING_NAME_PARTYCOMMANDER_FOLLOW = "Follow"
BINDING_NAME_PARTYCOMMANDER_HOLD = "Hold position"
BINDING_NAME_PARTYCOMMANDER_ATTACK = "Attack my target"
BINDING_NAME_PARTYCOMMANDER_REBUFF = "Rebuff"
BINDING_NAME_PARTYCOMMANDER_FLEE = "Flee and follow"
BINDING_NAME_PARTYCOMMANDER_CYCLE_SCOPE = "Cycle command scope (group, Wife, healers)"

local actions = {
  FOLLOW = { label = "Follow", command = "follow" },
  HOLD = { label = "Hold", command = "stay" },
  ATTACK = { label = "Attack", command = "attack" },
  REBUFF = { label = "Rebuff", command = "rebuff" },
  FLEE = { label = "Flee", command = "flee" },
}
local scopes = { "GROUP", "WIFE", "HEALERS" }

local function notify(message)
  DEFAULT_CHAT_FRAME:AddMessage("|cff6eb5ffParty Commander:|r " .. message)
end

local function chatChannel()
  if GetNumRaidMembers() > 0 then return "RAID" end
  if GetNumPartyMembers() > 0 then return "PARTY" end
  return nil
end

function commander:CompanionName()
  return PartyCommanderDB.companionName
end

function commander:ScopeName(scope)
  if scope == "WIFE" then return self:CompanionName() end
  if scope == "HEALERS" then return "healers" end
  return "the group"
end

function commander:ModifierScope()
  if IsControlKeyDown() then return "WIFE" end
  if IsShiftKeyDown() then return "HEALERS" end
  return "GROUP"
end

function commander:Execute(actionKey, scope)
  local action = actions[actionKey]
  if not action then return end
  scope = scope or self:ModifierScope()
  if scope == "WIFE" then
    SendChatMessage(action.command, "WHISPER", nil, self:CompanionName())
    notify(action.label .. " sent to " .. self:CompanionName() .. ".")
    return
  end
  local channel = chatChannel()
  if not channel then
    notify("Join a party or raid before commanding the group.")
    return
  end
  local command = action.command
  if scope == "HEALERS" then command = "@heal " .. command end
  SendChatMessage(command, channel)
  notify(action.label .. " sent to " .. self:ScopeName(scope) .. ".")
end

function commander:ControllerAction(actionKey)
  self:Execute(actionKey, PartyCommanderDB.controllerScope)
end

function commander:CycleControllerScope()
  local current = PartyCommanderDB.controllerScope
  for index, scope in ipairs(scopes) do
    if scope == current then
      PartyCommanderDB.controllerScope = scopes[(index % #scopes) + 1]
      notify("Controller scope: " .. self:ScopeName(PartyCommanderDB.controllerScope) .. ".")
      return
    end
  end
  PartyCommanderDB.controllerScope = "GROUP"
end

local function tooltip(button)
  GameTooltip:SetOwner(button, "ANCHOR_RIGHT")
  GameTooltip:SetText(button.action.label)
  GameTooltip:AddLine("Click: command the current party or raid", 1, 1, 1)
  GameTooltip:AddLine("Ctrl+Click: command " .. commander:CompanionName(), 0.7, 0.85, 1)
  GameTooltip:AddLine("Shift+Click: command healer bots", 0.7, 0.85, 1)
  GameTooltip:AddLine("Controller bindings use the selected controller scope.", 0.6, 0.6, 0.6)
  GameTooltip:Show()
end

local function createButton(parent, action, index)
  local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  button.action = action
  button:SetWidth(86)
  button:SetHeight(25)
  button:SetPoint("TOPLEFT", parent, "TOPLEFT", 8 + ((index - 1) * 89), -28)
  button:SetText(action.label)
  button:RegisterForClicks("AnyUp")
  button:SetScript("OnClick", function() commander:Execute(action.key) end)
  button:SetScript("OnEnter", tooltip)
  button:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

local function createFrame()
  local frame = CreateFrame("Frame", "PartyCommanderFrame", UIParent)
  frame:SetWidth(461)
  frame:SetHeight(62)
  frame:SetPoint("CENTER", UIParent, "CENTER", 0, -220)
  frame:SetMovable(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", function(self) self:StartMoving() end)
  frame:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
  frame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
  frame:SetBackdropColor(0.04, 0.07, 0.11, 0.92)
  local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  title:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -8)
  title:SetText("Party Commander  |  Click: group  ·  Ctrl: Wife  ·  Shift: healers")
  for index, key in ipairs({ "FOLLOW", "HOLD", "ATTACK", "REBUFF", "FLEE" }) do
    actions[key].key = key
    createButton(frame, actions[key], index)
  end
end

SLASH_PARTYCOMMANDER1 = "/partycommander"
SLASH_PARTYCOMMANDER2 = "/pc"
SlashCmdList.PARTYCOMMANDER = function(message)
  local command, value = string.match(message or "", "^(%S*)%s*(.-)%s*$")
  command = string.lower(command or "")
  if command == "show" then PartyCommanderFrame:Show()
  elseif command == "hide" then PartyCommanderFrame:Hide()
  elseif command == "scope" then commander:CycleControllerScope()
  elseif command == "wife" and value ~= "" then
    PartyCommanderDB.companionName = value
    notify("Companion set to " .. value .. ".")
  else
    notify("/pc show | hide | scope | wife <character name>")
  end
end

local startup = CreateFrame("Frame")
startup:RegisterEvent("PLAYER_LOGIN")
startup:SetScript("OnEvent", function()
  PartyCommanderDB = PartyCommanderDB or {}
  PartyCommanderDB.companionName = PartyCommanderDB.companionName or "Wife"
  PartyCommanderDB.controllerScope = PartyCommanderDB.controllerScope or "GROUP"
  createFrame()
end)
