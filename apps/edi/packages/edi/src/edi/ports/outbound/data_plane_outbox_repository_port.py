from typing import Protocol

from seedwork.domain.types import JsonValue


class DataPlaneOutboxRepositoryPort(Protocol):
    """
    Data Plane Outbox Repository Port for pipeline events.
    """

    async def append_event(
        self, event_type: str, payload: dict[str, JsonValue], idempotency_key: str | None = None
    ) -> None: ...
