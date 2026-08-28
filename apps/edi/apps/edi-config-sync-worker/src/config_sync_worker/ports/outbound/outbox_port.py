from typing import Any, Protocol


class OutboxEvent(Protocol):
    @property
    def id(self) -> Any: ...
    @property
    def event_type(self) -> str: ...
    @property
    def body(self) -> dict[str, Any]: ...


class OutboxPort(Protocol):
    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """Publishes an event to the outbox queue."""
        ...

    async def __aenter__(self) -> "OutboxPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None: ...
