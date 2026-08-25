import abc
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel


class IdentityEventMessage(BaseModel):
    """
    Schema for an incoming domain event received from the event broker.
    This exactly matches the fields in EventEnvelope.
    """

    id: str
    source: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
    tenant_id: str | None = None


class IdentityEventListenerPort(abc.ABC):
    """
    Port for consuming incoming Identity events.
    """

    @asynccontextmanager
    @abc.abstractmethod
    async def process_next_event(self) -> AsyncGenerator[IdentityEventMessage | None, None]:
        """
        Yields the next available event message.
        If an exception is raised inside the context manager by the consumer,
        the event is NOT acknowledged/deleted and will be retried.
        """
        yield None

    async def __aenter__(self) -> "IdentityEventListenerPort":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass
