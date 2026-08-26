#include "SoulBridgeQueue.h"

#include <cassert>
#include <stdexcept>

int main()
{
    bool rejectedZero = false;
    try
    {
        soulforge::SoulBridgeQueue invalid(0);
    }
    catch (std::invalid_argument const&)
    {
        rejectedZero = true;
    }
    assert(rejectedZero);

    soulforge::SoulBridgeQueue queue(1);
    assert(queue.TryPush({"first", "{}"}));
    assert(!queue.TryPush({"second", "{}"}));
    assert(queue.Dropped() == 1);

    auto event = queue.TryPop();
    assert(event.has_value());
    assert(event->eventId == "first");
    assert(queue.Size() == 0);
    assert(!queue.TryPop().has_value());
    return 0;
}
