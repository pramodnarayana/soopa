from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class UcpEventMessage:
    id: str
    event_type: str
    tenant_id: str
    payload: dict[str, Any]


class UcpEventConsumerPort(Protocol):
    """
    Protocol for inbound AWS SDK adapters (SQS Consumers).
    """

    async def __aenter__(self) -> "UcpEventConsumerPort": ...
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...

    def process_next_event(self) -> AbstractAsyncContextManager[UcpEventMessage | None]: ...
