from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class AckableMessage:
    payload: JsonDict
    ack: Callable[[], Awaitable[None]]
    nack: Callable[[], Awaitable[None]]
