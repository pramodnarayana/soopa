from typing import Protocol

from database.events import EventEnvelope
from outbox.ports.outbox_repository_port import OutboxRepositoryPort


class NotificationOutboxRepositoryPort(OutboxRepositoryPort, Protocol):
    """
    Port for managing notification outbox persistence.
    """

    async def save(self, message: EventEnvelope) -> None: ...
