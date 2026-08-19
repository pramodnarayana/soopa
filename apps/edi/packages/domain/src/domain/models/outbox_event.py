from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
