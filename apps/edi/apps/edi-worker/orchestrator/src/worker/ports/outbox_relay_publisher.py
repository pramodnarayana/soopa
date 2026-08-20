from typing import Any, Protocol, Self

from worker.ports.outbox_relay_repository import RelayOutboxEvent


class OutboxRelayPublisherPort(Protocol):
    async def publish(self, event: RelayOutboxEvent) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None: ...
