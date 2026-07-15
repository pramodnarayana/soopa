from typing import Any, Protocol
from uuid import UUID


class OutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: UUID | None = None,
    ) -> UUID: ...
