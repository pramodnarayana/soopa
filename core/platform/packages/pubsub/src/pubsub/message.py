from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class AckableMessage:
    payload: dict[str, Any]
    ack: Callable[[], Awaitable[None]]
    nack: Callable[[], Awaitable[None]]
