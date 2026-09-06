from typing import Protocol

from pubsub.events import EventEnvelope


class NotificationOutboxRepositoryPort(Protocol):
    """
    Port for managing notification outbox persistence.
    """

    async def save(self, message: EventEnvelope) -> None: ...
