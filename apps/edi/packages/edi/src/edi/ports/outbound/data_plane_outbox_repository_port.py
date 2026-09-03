from typing import Protocol

from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.domain.types import JsonValue


class DataPlaneOutboxRepositoryPort(OutboxRepositoryPort, Protocol):
    """
    Data Plane Outbox Repository Port for pipeline events.
    Extends the base OutboxRepositoryPort with pipeline-specific methods.
    """

    async def append_event(
        self, event_type: str, payload: dict[str, JsonValue], idempotency_key: str | None = None
    ) -> None: ...

    async def claim_delivery_outbox_event(self, idempotency_key: str) -> str | None: ...

    async def mark_delivery_success(self, idempotency_key: str, owner_token: str) -> None: ...

    async def mark_delivery_failure(self, idempotency_key: str, owner_token: str) -> None: ...
