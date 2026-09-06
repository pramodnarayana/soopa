from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class UcpEventMessage:
    id: str
    event_type: str
    tenant_id: str
    payload: JsonDict


class UcpEventConsumerPort(Protocol):
    """
    Protocol for inbound AWS SDK adapters (SQS Consumers).
    """

    async def __aenter__(self) -> "UcpEventConsumerPort": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None: ...

    def process_next_event(self) -> AbstractAsyncContextManager[UcpEventMessage | None]: ...
