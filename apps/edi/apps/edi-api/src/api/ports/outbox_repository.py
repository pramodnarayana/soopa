from typing import Any, Protocol

from domain.events import ProvisioningEvent
from platform_schemas.edi_events import EdiEventType


class ControlPlaneOutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self,
        event: ProvisioningEvent,
        idempotency_key: str | None = None,
    ) -> str: ...


class DataPlaneOutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self,
        tenant_id: str,
        event_type: EdiEventType | str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str: ...
