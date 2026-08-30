import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from outbox.domain.constants import OutboxStatus
from seedwork import generate_id
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.domain.constants import DomainIdPrefix
from edi.domain.events import PipelineEventType


@dataclass
class DataPlaneOutboxBuilder:
    session: AsyncSession
    tenant_id: str = "ten_default_123"
    event_type: str = PipelineEventType.TRANSFORM_EVENT.value
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = OutboxStatus.PENDING.value
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC) - timedelta(minutes=6))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    async def create(self, **kwargs) -> DataPlaneOutbox:
        outbox_event = DataPlaneOutbox(
            id=kwargs.get("id", generate_id(DomainIdPrefix.DP_OUTBOX)),
            tenant_id=kwargs.get("tenant_id", self.tenant_id),
            idempotency_key=kwargs.get("idempotency_key", f"idemp_{uuid.uuid4()}"),
            event_type=kwargs.get("event_type", self.event_type),
            payload=kwargs.get("payload", self.payload),
            status=kwargs.get("status", self.status),
            attempts=kwargs.get("attempts", self.attempts),
            created_at=kwargs.get("created_at", self.created_at),
            updated_at=kwargs.get("updated_at", self.updated_at),
        )
        self.session.add(outbox_event)
        await self.session.flush()
        return outbox_event

    async def create_batch(self, count: int) -> list[DataPlaneOutbox]:
        events = []
        for _ in range(count):
            events.append(await self.create())
        return events
