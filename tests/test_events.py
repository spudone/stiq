import pytest
import asyncio
from stiq.events import EventBus


@pytest.mark.asyncio
async def test_event_bus_pub_sub():
    bus = EventBus()
    queue1 = asyncio.Queue()
    queue2 = asyncio.Queue()

    # Test subscribe
    bus.subscribe(queue1)
    bus.subscribe(queue2)
    assert len(bus.subscribers) == 2

    # Test publish
    bus.publish("market", {"is_open": True})

    msg1 = await queue1.get()
    msg2 = await queue2.get()

    assert msg1 == {"type": "market", "data": {"is_open": True}}
    assert msg2 == {"type": "market", "data": {"is_open": True}}

    # Test unsubscribe
    bus.unsubscribe(queue1)
    assert len(bus.subscribers) == 1

    bus.publish("quotes", [{"symbol": "AAPL"}])

    msg2_again = await queue2.get()
    assert msg2_again == {"type": "quotes", "data": [{"symbol": "AAPL"}]}
    assert queue1.empty()


@pytest.mark.asyncio
async def test_event_bus_queue_full():
    bus = EventBus()
    queue = asyncio.Queue(maxsize=1)
    bus.subscribe(queue)

    # Fill the queue
    bus.publish("market", {"is_open": True})
    assert queue.full()

    # Publish again to full queue, shouldn't raise exception
    bus.publish("market", {"is_open": False})

    # Message should be the first one
    msg = await queue.get()
    assert msg["data"]["is_open"] is True
