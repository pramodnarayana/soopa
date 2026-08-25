from typing import Any, Protocol, Self

from platform_orm.events import EventEnvelope


class OutboxPublisherPort(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None: ...
