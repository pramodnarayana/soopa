from typing import Protocol

from ..domain.models.outbox_event import OutboxEvent


class OutboxPublisherPort(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...
