from typing import Protocol

from seedwork.events import EventEnvelope


class NotificationOutboxRepositoryPort(Protocol):
    """
    Port for managing notification outbox persistence.
    """

    async def save(self, message: EventEnvelope) -> None: ...
