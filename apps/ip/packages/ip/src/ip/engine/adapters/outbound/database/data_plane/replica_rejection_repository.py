"""SQLAlchemy repository adapter for Layer 2 ReplicaRejection audit ledger."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import replica_rejection_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRejectionModel
from ip.engine.domain.replication.replica_record import ReplicaRejection
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyReplicaRejectionRepository(
    TenantSqlAlchemyRepository, ReplicaRejectionRepositoryPort
):
    """Repository persisting rejected L2 records into the replica_rejections table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: ReplicaRejectionModel) -> ReplicaRejection:
        return replica_rejection_to_domain(record)

    @staticmethod
    def _to_orm_model(rejection: ReplicaRejection) -> ReplicaRejectionModel:
        return ReplicaRejectionModel(
            id=rejection.id,
            tenant_id=rejection.tenant_id,
            connection_id=rejection.connection_id,
            stream=rejection.stream,
            inbound_record_id=rejection.inbound_record_id,
            record_index=rejection.record_index,
            reason=rejection.reason,
            detail=rejection.detail,
            trace_id=rejection.trace_id,
            correlation_id=rejection.correlation_id,
            parent_trace_id=rejection.parent_trace_id,
            original_trace_id=rejection.original_trace_id,
            replay_count=rejection.replay_count,
            created_at=rejection.created_at,
        )

    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        """Persists a batch of rejected records."""
        for r in rejections:
            self._session.add(self._to_orm_model(r))
        await self._session.flush()

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[ReplicaRejection]:
        stmt = (
            select(ReplicaRejectionModel)
            .where(
                ReplicaRejectionModel.trace_id == trace_id,
                ReplicaRejectionModel.tenant_id == tenant_id,
            )
            .order_by(ReplicaRejectionModel.created_at.asc())
        )
        res = await self._session.execute(stmt)
        return [self._to_domain_model(r) for r in res.scalars().all()]
