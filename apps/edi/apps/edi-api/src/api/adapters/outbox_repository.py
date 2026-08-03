import uuid
from typing import Any

from database.base_repository import GlobalSqlAlchemyRepository, TenantSqlAlchemyRepository
from database.models.control_plane import ControlPlaneOutbox
from domain.events import ProvisioningEvent

from api.ports.outbox_repository import (
    ControlPlaneOutboxRepositoryPort,
    DataPlaneOutboxRepositoryPort,
)


class SqlAlchemyOutboxRepositoryMixin:
    session: Any
    model_class: Any
    id_prefix: str = "obevt_"

    async def publish_outbox_event(
        self,
        tenant_id: str,
        event_type: Any,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str:
        tid_str = tenant_id if tenant_id is not None else None
        event_type_str = event_type.value if hasattr(event_type, "value") else str(event_type)
        event_id = f"{self.id_prefix}{uuid.uuid4().hex}"
        record = self.model_class(
            id=event_id,
            tenant_id=tid_str,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            event_type=event_type_str,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return event_id


class SqlAlchemyControlPlaneOutboxRepository(
    SqlAlchemyOutboxRepositoryMixin, GlobalSqlAlchemyRepository, ControlPlaneOutboxRepositoryPort
):
    """
    Outbox repository for the Control Plane (Global DB).
    Writes provisioning events (AS2_PARTNER_CREATED, etc.) that are later
    polled by the Provisioning Worker to replicate config to tenant shards.
    """

    def __init__(self, session: Any, model_class: Any = ControlPlaneOutbox) -> None:
        super().__init__(session)
        self.model_class = model_class
        self.id_prefix = "edi_cobevt_"

    async def publish_outbox_event(  # type: ignore[override]
        self,
        event: ProvisioningEvent,
        idempotency_key: str | None = None,
    ) -> str:
        from sqlalchemy import text

        event_id = await super().publish_outbox_event(
            tenant_id=event.tenant_id,
            event_type=str(
                event.event_type.value if hasattr(event.event_type, "value") else event.event_type
            ),
            payload=event.model_dump(mode="json"),
            idempotency_key=idempotency_key,
        )
        await self.session.execute(
            text("SELECT pg_notify('edi_outbox_channel', :event_id)"),
            {"event_id": event_id},
        )
        return event_id


class SqlAlchemyDataPlaneOutboxRepository(
    SqlAlchemyOutboxRepositoryMixin, TenantSqlAlchemyRepository, DataPlaneOutboxRepositoryPort
):
    """
    Outbox repository for the Data Plane (Tenant Shard).
    Writes pipeline events (TRANSFORM_EVENT, DELIVER_EVENT, etc.) consumed
    by the CDC Sweeper, which is configurable through the Scheduler UI.
    """

    def __init__(self, session: Any) -> None:
        from database.models.data_plane import DataPlaneOutbox

        super().__init__(session)
        self.model_class = DataPlaneOutbox
        self.id_prefix = "edi_dobevt_"
