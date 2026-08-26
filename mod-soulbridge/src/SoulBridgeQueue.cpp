#include "SoulBridgeQueue.h"

#include <stdexcept>
#include <utility>

namespace soulforge
{
SoulBridgeQueue::SoulBridgeQueue(std::size_t capacity) : capacity_(capacity)
{
    if (capacity == 0)
        throw std::invalid_argument("queue capacity must be positive");
}

bool SoulBridgeQueue::TryPush(EventEnvelope event)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.size() >= capacity_)
    {
        ++dropped_;
        return false;
    }

    queue_.push_back(std::move(event));
    return true;
}

std::optional<EventEnvelope> SoulBridgeQueue::TryPop()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.empty())
        return std::nullopt;

    EventEnvelope event = std::move(queue_.front());
    queue_.pop_front();
    return event;
}

std::size_t SoulBridgeQueue::Size() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
}

std::size_t SoulBridgeQueue::Dropped() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return dropped_;
}
} // namespace soulforge
