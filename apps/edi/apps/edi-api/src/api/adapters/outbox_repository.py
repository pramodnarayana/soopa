import uuid
from typing import Any
from uuid import UUID

from database.base_repository import GlobalSqlAlchemyRepository, TenantSqlAlchemyRepository
from database.models.control_plane import ControlPlaneOutbox

from api.ports.outbox_repository import OutboxRepositoryPort


class SqlAlchemyOutboxRepositoryMixin:
    session: Any
    model_class: Any

    async def publish_outbox_event(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: UUID | None = None,
    ) -> UUID:
        tid_str = str(tenant_id) if tenant_id is not None else None
        event_id = uuid.uuid4()
        record = self.model_class(
            id=event_id,
            tenant_id=tid_str,
            idempotency_key=idempotency_key or uuid.uuid4(),
            event_type=event_type,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return event_id


class SqlAlchemyControlPlaneOutboxRepository(
    SqlAlchemyOutboxRepositoryMixin, GlobalSqlAlchemyRepository, OutboxRepositoryPort
):
    """
    Outbox repository for the Control Plane (Global DB).
    Writes provisioning events (AS2_PARTNER_CREATED, etc.) that are later
    polled by the Provisioning Worker to replicate config to tenant shards.
    """

    def __init__(self, session: Any, model_class: Any = ControlPlaneOutbox) -> None:
        super().__init__(session)
        self.model_class = model_class


class SqlAlchemyDataPlaneOutboxRepository(
    SqlAlchemyOutboxRepositoryMixin, TenantSqlAlchemyRepository, OutboxRepositoryPort
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
