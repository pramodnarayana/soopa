import structlog
from seedwork import generate_id
from seedwork.domain.types import JsonValue
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
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
        self, event_type: str, payload: dict[str, JsonValue], idempotency_key: str | None = None
    ) -> None:
        """Appends a new event to the Data Plane Outbox (idempotent on conflict)."""
        stmt = (
            insert(DataPlaneOutbox)
            .values(
                id=generate_id(DomainIdPrefix.EDI_DP_OUTBOX),
                idempotency_key=str(idempotency_key)
                if idempotency_key
                else generate_id(SystemIdPrefix.GENERIC),
                event_type=event_type,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(stmt)
        await self._session.flush()
