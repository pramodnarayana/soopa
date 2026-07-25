from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol


class OutboxEvent(Protocol):
    @property
    def id(self) -> Any: ...
    @property
    def event_type(self) -> str: ...
    @property
    def payload(self) -> dict[str, Any]: ...


class OutboxPort(Protocol):
    def process_next_event(self) -> AbstractAsyncContextManager[OutboxEvent | None]:
        """Context manager that yields the next pending event, or None."""
        ...

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """Publishes an event to the outbox queue."""
        ...
