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
from typing import Any


class EventBus:
    def __init__(self):
        self.subscribers: set[asyncio.Queue] = set()

    def subscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.add(queue)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def publish(self, event_type: str, data: Any) -> None:
        """Publishes a structured event to all connected queues."""
        message = {"type": event_type, "data": data}
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass


event_bus = EventBus()
