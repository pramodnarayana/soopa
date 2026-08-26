from typing import Protocol

from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from platform_orm.events import EventEnvelope


class NotificationOutboxRepositoryPort(OutboxRepositoryPort, Protocol):
    """
    Port for managing notification outbox persistence.
    """

    async def save(self, message: EventEnvelope) -> None: ...
