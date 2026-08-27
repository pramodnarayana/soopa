from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from pydantic import BaseModel


class IdentityEventMessage(BaseModel):
    """
    Schema for an incoming domain event received from the event broker.
    This exactly matches the fields in EventEnvelope.
    """

    id: str
    source: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
    tenant_id: str | None = None


class IdentityEventConsumerPort(Protocol):
    """
    Protocol for inbound AWS SDK adapters (SQS Consumers).
    """

    async def __aenter__(self) -> "IdentityEventConsumerPort": ...
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...

    def process_next_event(self) -> AbstractAsyncContextManager[IdentityEventMessage | None]: ...
