import structlog
from outbox.domain.constants import OutboxStatus
from seedwork import generate_id
from seedwork.domain.types import JsonValue
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.domain.enums import EdiOutboxSource
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort

logger = structlog.get_logger(__name__)

_DELIVERY_LEASE_MINUTES = 5


class SqlAlchemyDataPlaneOutboxRepository(DataPlaneOutboxRepositoryPort):
    """
    Concrete implementation of DataPlaneOutboxRepositoryPort using SQLAlchemy AsyncSession.

    Responsible for all transactional outbox operations: appending events, claiming
    delivery leases, and marking delivery outcomes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, JsonValue],
        idempotency_key: str | None = None,
    ) -> EventEnvelope:
        """Appends a new event to the Data Plane Outbox (idempotent on conflict)."""
        event_id = generate_id(DomainIdPrefix.EDI_DP_OUTBOX)
        ik = str(idempotency_key) if idempotency_key else generate_id(SystemIdPrefix.GENERIC)

        tenant_id = tenant_id.strip()
        if not tenant_id:
            raise ValueError("tenant_id is mandatory in the outbox payload.")

        stmt = (
            insert(DataPlaneOutbox)
            .values(
                id=event_id,
                idempotency_key=ik,
                event_type=event_type,
                payload=payload,
                tenant_id=tenant_id,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

        return EventEnvelope(
            id=event_id,
            source=EdiOutboxSource.EDI_DATA_PLANE,
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=ik,
        )

    async def mark_completed(self, event_id: str) -> None:
        stmt = (
            update(DataPlaneOutbox)
            .where(DataPlaneOutbox.id == event_id)
            .values(status=OutboxStatus.PROCESSED.value)
        )
        await self._session.execute(stmt)
