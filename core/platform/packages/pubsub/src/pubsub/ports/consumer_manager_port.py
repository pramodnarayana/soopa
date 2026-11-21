"""Universal Consumer Manager port protocol."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from seedwork.domain.types import JsonDict

from pubsub.domain.dtos import AckableMessage
from pubsub.domain.enums import ConsumerVerdict
from pubsub.enums import ConsumerOutcome

MessageHandler = (
    Callable[[AckableMessage], Awaitable[ConsumerVerdict | None]]
    | Callable[[JsonDict], Awaitable[ConsumerOutcome | None]]
    | Callable[..., Awaitable[object]]
)


@runtime_checkable
class ConsumerManagerPort(Protocol):
    """Autonomous background message pump polling a broker and dispatching to handlers."""

    def start(self) -> None:
        """Starts the background worker pump."""
        ...

    async def stop(self) -> None:
        """Gracefully drains and stops the polling loop."""
        ...

    async def health_check(self) -> bool:
        """Returns True if the connection and polling loop are healthy."""
        ...

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Returns the internal asyncio task for the consumer loop."""
        ...

    def background_tasks(self) -> list[asyncio.Task[object]]:
        """Returns background asyncio tasks associated with this consumer."""
        ...
