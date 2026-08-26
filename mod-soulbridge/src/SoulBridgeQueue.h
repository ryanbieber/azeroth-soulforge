#pragma once

#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <string>

namespace soulforge
{
struct EventEnvelope
{
    std::string eventId;
    std::string payload;
};

// A small non-blocking boundary for world hooks. Network transport belongs to
// a separate worker and is intentionally absent from this class.
class SoulBridgeQueue
{
public:
    explicit SoulBridgeQueue(std::size_t capacity);

    bool TryPush(EventEnvelope event);
    std::optional<EventEnvelope> TryPop();
    std::size_t Size() const;
    std::size_t Dropped() const;

private:
    const std::size_t capacity_;
    mutable std::mutex mutex_;
    std::deque<EventEnvelope> queue_;
    std::size_t dropped_ = 0;
};
} // namespace soulforge
