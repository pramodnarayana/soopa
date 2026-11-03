from outbox.domain.constants import OutboxStatus
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import insert, select

from database.exceptions import DuplicateEntityError
from database.interceptors import intercept_db_errors
from database.types import GlobalSession
from edi.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.domain.events import OutboxEvent
from edi.domain.exceptions import IdempotencyConflictError
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)


class SqlAlchemyControlPlaneOutboxRepository(
    GlobalSqlAlchemyRepository, ControlPlaneOutboxRepositoryPort
):
    """
    Outbox repository for the Control Plane (Global DB).
    Provides idempotency reservation management and lookup for provisioning commands;
    domain events are persisted atomically via `GlobalSqlAlchemyRepository._drain_events`.
    """

    def __init__(
        self,
        session: GlobalSession,
        model_class: type[ControlPlaneOutbox] = ControlPlaneOutbox,
    ) -> None:
        super().__init__(session)
        self.model_class = model_class

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None:
        stmt = select(self.model_class).where(self.model_class.idempotency_key == idempotency_key)
        res = await self.session.execute(stmt)
        db_model = res.scalar_one_or_none()
        if not db_model:
            return None

        return OutboxEvent(
            id=str(db_model.id),
            tenant_id=db_model.tenant_id,
            event_type=db_model.event_type,
            payload=db_model.payload,
            idempotency_key=db_model.idempotency_key,
        )

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None:
        insert_stmt = insert(self.model_class).values(
            id=f"reservation_{idempotency_key}",
            tenant_id=tenant_id,
            idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            event_type="RESERVATION",
            payload={"fingerprint": fingerprint},
            status=OutboxStatus.RESERVED,
            attempts=0,
        )
        try:
            async with self.session.begin_nested(), intercept_db_errors():
                await self.session.execute(insert_stmt)
                await self.flush()
        except DuplicateEntityError as e:
            raise IdempotencyConflictError() from e
