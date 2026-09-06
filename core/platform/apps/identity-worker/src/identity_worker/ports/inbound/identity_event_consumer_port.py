from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class IdentityEventMessage:
    """
    Schema for an incoming domain event received from the event broker.
    This exactly matches the fields in EventEnvelope.
    """

    id: str
    source: str
    event_type: str
    payload: JsonDict
    idempotency_key: str | None = None
    tenant_id: str | None = None


class IdentityEventConsumerPort(Protocol):
    """
    Protocol for inbound AWS SDK adapters (SQS Consumers).
    """

    async def __aenter__(self) -> "IdentityEventConsumerPort": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    def process_next_event(self) -> AbstractAsyncContextManager[IdentityEventMessage | None]: ...
