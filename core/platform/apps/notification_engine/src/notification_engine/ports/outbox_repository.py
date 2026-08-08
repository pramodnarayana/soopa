from typing import Protocol

from ..domain.models import NotificationOutboxEvent


class NotificationOutboxRepositoryPort(Protocol):
    """
    Port for managing notification outbox persistence.
    """

    async def save(self, message: NotificationOutboxEvent) -> None: ...

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int: ...

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[NotificationOutboxEvent]: ...

    async def mark_completed(self, message_id: str, worker_id: str) -> None: ...

    async def mark_failed(self, message_id: str, worker_id: str, error_reason: str) -> None: ...
