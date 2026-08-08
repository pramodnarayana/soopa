from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    tenant_id: str | None
    event_type: str
    idempotency_key: str | None
    payload: dict[str, Any]
