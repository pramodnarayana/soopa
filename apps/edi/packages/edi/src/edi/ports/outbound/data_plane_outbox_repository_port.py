from typing import Protocol

from seedwork.domain.types import JsonValue
from seedwork.events import EventEnvelope


class DataPlaneOutboxRepositoryPort(Protocol):
    """
    Data Plane Outbox Repository Port for pipeline events.
    """

    async def append_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, JsonValue],
        idempotency_key: str | None = None,
    ) -> EventEnvelope: ...

    async def mark_completed(self, event_id: str) -> None: ...
