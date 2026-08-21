from typing import Protocol

from ucp.domain.models.outbox_event import OutboxEvent


class OutboxRepositoryPort(Protocol):
    async def sweep_stuck_events(self, lock_lease_ms: int) -> int: ...

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[OutboxEvent]: ...

    async def mark_completed(self, event_id: str, worker_id: str) -> None: ...

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None: ...
