from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from pydantic import AliasChoices, BaseModel, Field


class UcpEventMessage(BaseModel):
    id: str = Field(validation_alias=AliasChoices("eventId", "id"))
    event_type: str = Field(validation_alias=AliasChoices("eventType", "event_type"))
    tenant_id: str = Field(validation_alias=AliasChoices("tenantId", "tenant_id"))
    payload: dict[str, Any]


class UcpEventConsumerPort(Protocol):
    """
    Protocol for inbound AWS SDK adapters (SQS Consumers).
    """

    async def __aenter__(self) -> "UcpEventConsumerPort": ...
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...

    def process_next_event(self) -> AbstractAsyncContextManager[UcpEventMessage | None]: ...
