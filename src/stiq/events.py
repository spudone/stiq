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
