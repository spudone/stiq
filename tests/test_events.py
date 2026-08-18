"""
Stiq - Stock Ticker
Copyright (C) 2026 spudone

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import asyncio

import pytest

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
