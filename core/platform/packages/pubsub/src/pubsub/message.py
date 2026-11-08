from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict


class NackCallbackPort(Protocol):
    """Protocol for broker negative-acknowledgment with optional visibility timeout."""

    async def __call__(self, *, visibility_timeout_seconds: int | None = None) -> None: ...


@dataclass(frozen=True)
class AckableMessage:
    payload: JsonDict
    ack: Callable[[], Awaitable[None]]
    nack: NackCallbackPort
