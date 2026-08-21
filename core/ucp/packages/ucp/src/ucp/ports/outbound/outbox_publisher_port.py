from typing import Any, Protocol, Self

from ucp.domain.models.outbox_event import OutboxEvent


class OutboxPublisherPort(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None: ...
