import uuid
from typing import Any

from database.base_repository import GlobalSqlAlchemyRepository, TenantSqlAlchemyRepository

# Shared prefix constants for Data Plane IDs
from database.constants import DATA_PLANE_OUTBOX_EVENT_PREFIX
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

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> Any | None:
        from sqlalchemy import select

        stmt = select(self.model_class).where(self.model_class.idempotency_key == idempotency_key)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None:
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError

        from api.core.exceptions import IdempotencyConflictError

        insert_stmt = insert(self.model_class).values(
            id=f"reservation_{idempotency_key}",
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            event_type="RESERVATION",
            payload={"fingerprint": fingerprint},
            status="RESERVED",
            attempts=0,
        )
        try:
            await self.session.execute(insert_stmt)
            await self.session.flush()
        except IntegrityError as e:
            raise IdempotencyConflictError() from e


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
        self.id_prefix = DATA_PLANE_OUTBOX_EVENT_PREFIX
