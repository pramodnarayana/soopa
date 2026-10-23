"""SQLAlchemy repository adapter for Layer 2 ReplicaRejection audit ledger."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRejectionModel
from ip.engine.domain.models.replica_record import ReplicaRejection
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyReplicaRejectionRepository(
    TenantSqlAlchemyRepository, ReplicaRejectionRepositoryPort
):
    """Repository persisting rejected L2 records into the replica_rejections table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        """Persists a batch of rejected records."""
        for r in rejections:
            orm = ReplicaRejectionModel(
                id=r.id,
                tenant_id=r.tenant_id,
                connection_id=r.connection_id,
                stream=r.stream,
                inbound_record_id=r.inbound_record_id,
                record_index=r.record_index,
                reason=r.reason,
                detail=r.detail,
                trace_id=r.trace_id,
                created_at=r.created_at,
            )
            self._session.add(orm)
        await self._session.flush()
