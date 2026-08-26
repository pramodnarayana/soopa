from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    """
    Standard Enterprise Event Envelope (CloudEvents compliant).
    Must be used by all Bounded Contexts when publishing events via the Outbox.
    """

    id: str
    source: str
    event_type: str
    tenant_id: str | None
    idempotency_key: str | None
    payload: dict[str, Any]
