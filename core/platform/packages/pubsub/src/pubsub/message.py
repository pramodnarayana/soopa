from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SqsMessagePayload:
    """
    A generic typed envelope that enforces structure for idempotency while holding any payload.
    """

    idempotency_key: str | None = None
    tenant_id: str | None = None
    event_type: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AckableMessage:
    payload: SqsMessagePayload
    ack: Callable[[], Awaitable[None]]
    nack: Callable[[], Awaitable[None]]
