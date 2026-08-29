from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable

from pubsub.message import AckableMessage


@runtime_checkable
class MessageConsumerPort(Protocol):
    """
    Port that abstracts message consumption from any broker (SQS, Kafka, in-memory).

    Implementations must support both one-shot usage (via a one-off client)
    and long-lived reuse (via the async context manager for connection pooling).
    """

    async def __aenter__(self) -> "MessageConsumerPort": ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...

    @asynccontextmanager
    def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]: ...
