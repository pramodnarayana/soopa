from dataclasses import dataclass

from edi.domain.types import JsonValue


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    tenant_id: str
    event_type: str
    payload: dict[str, JsonValue]
    idempotency_key: str | None = None
