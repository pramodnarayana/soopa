from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class RelayOutboxEvent:
    id: str
    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None


class OutboxRelayRepositoryPort(Protocol):
    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[RelayOutboxEvent]: ...

    async def mark_completed(self, event_id: str, worker_id: str) -> None: ...

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None: ...

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int: ...
