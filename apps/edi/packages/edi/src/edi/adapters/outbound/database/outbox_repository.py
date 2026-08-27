import uuid
from typing import Any

from edi.adapters.outbound.database.base_repository import (
    GlobalSqlAlchemyRepository,
    TenantSqlAlchemyRepository,
)

# Shared prefix constants for Data Plane IDs
from edi.adapters.outbound.database.constants import DATA_PLANE_OUTBOX_EVENT_PREFIX
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort


class SqlAlchemyOutboxRepositoryMixin:
    session: Any
    model_class: Any
    id_prefix: str = "obevt_"

    async def _publish_record(
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

    async def publish_outbox_events_bulk(
        self,
        tenant_id: str,
        events: list[dict[str, Any]],
    ) -> list[str]:
        tid_str = tenant_id if tenant_id is not None else None
        event_ids = []
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        insert_stmts = []
        for event in events:
            event_type = event["event_type"]
            event_type_str = event_type.value if hasattr(event_type, "value") else str(event_type)
            event_id = f"{self.id_prefix}{uuid.uuid4().hex}"

            insert_stmts.append(
                {
                    "id": event_id,
                    "tenant_id": tid_str,
                    "idempotency_key": event.get("idempotency_key") or str(uuid.uuid4()),
                    "event_type": event_type_str,
                    "payload": event.get("payload", {}),
                    "status": "PENDING",
                }
            )
            event_ids.append(event_id)

        if insert_stmts:
            stmt = pg_insert(self.model_class).values(insert_stmts)
            stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
            await self.session.execute(stmt)

        return event_ids


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

    async def publish_outbox_event(
        self,
        event: ProvisioningEvent,
        idempotency_key: str | None = None,
    ) -> str:
        from sqlalchemy import select

        from database.outbox_serializer import serialize_domain_event

        serialized_event = serialize_domain_event(event)
        if idempotency_key:
            result = await self.session.execute(
                select(self.model_class).where(
                    self.model_class.idempotency_key == idempotency_key,
                    self.model_class.status == "RESERVED",
                )
            )
            reservation = result.scalar_one_or_none()
            if reservation is not None:
                reservation.event_type = str(
                    event.event_type.value
                    if hasattr(event.event_type, "value")
                    else event.event_type
                )
                reservation.payload = {**reservation.payload, **serialized_event}
                reservation.status = "PENDING"
                await self.session.flush()
                return str(reservation.id)

        event_id = await self._publish_record(
            tenant_id=event.tenant_id,
            event_type=str(
                event.event_type.value if hasattr(event.event_type, "value") else event.event_type
            ),
            payload=serialized_event,
            idempotency_key=idempotency_key,
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

        from edi.domain.exceptions import IdempotencyConflictError

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
            async with self.session.begin_nested():
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
        from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox

        super().__init__(session)
        self.model_class = DataPlaneOutbox
        self.id_prefix = DATA_PLANE_OUTBOX_EVENT_PREFIX

    async def publish_outbox_event(
        self,
        tenant_id: str,
        event_type: Any,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str:
        return await self._publish_record(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )
