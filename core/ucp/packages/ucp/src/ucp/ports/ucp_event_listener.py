from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from pydantic import AliasChoices, BaseModel, Field


class UcpEventMessage(BaseModel):
    id: str = Field(validation_alias=AliasChoices("eventId", "id"))
    event_type: str = Field(validation_alias=AliasChoices("eventType", "event_type"))
    tenant_id: str = Field(validation_alias=AliasChoices("tenantId", "tenant_id"))
    payload: dict[str, Any]


class UcpEventListenerPort(Protocol):
    """
    Port for an inbound asynchronous stream of UCP domain events.
    Yields events one by one, managing acknowledgment implicitly on yield exit.
    """

    def process_next_event(self) -> AbstractAsyncContextManager[UcpEventMessage | None]: ...
