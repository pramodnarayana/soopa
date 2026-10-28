"""SQLAlchemy repository adapter for NormalizationRejection and ShadowDiff on tenant shards."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import (
    normalization_rejection_to_domain,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    NormalizationRejectionModel,
    NormalizationShadowDiffModel,
)
from ip.engine.domain.normalization import (
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyNormalizationRejectionRepository(
    TenantSqlAlchemyRepository, NormalizationRejectionRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of NormalizationRejectionRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_orm_model(rejection: NormalizationRejectionEntry) -> NormalizationRejectionModel:
        return NormalizationRejectionModel(
            id=rejection.id,
            tenant_id=rejection.tenant_id,
            replica_record_id=rejection.replica_record_id,
            stream=rejection.stream,
            transformation_id=rejection.transformation_id,
            transformation_version=rejection.transformation_version,
            reason_code=rejection.reason_code,
            field_path=rejection.field_path,
            detail=rejection.detail,
            trace_id=rejection.trace_id,
            correlation_id=rejection.correlation_id,
            created_at=rejection.created_at,
        )

    @staticmethod
    def _to_domain_model(record: NormalizationRejectionModel) -> NormalizationRejectionEntry:
        return normalization_rejection_to_domain(record)

    @staticmethod
    def _shadow_diff_to_orm_model(
        diff: NormalizationShadowDiffEntry,
    ) -> NormalizationShadowDiffModel:
        return NormalizationShadowDiffModel(
            id=diff.id,
            tenant_id=diff.tenant_id,
            replica_record_id=diff.replica_record_id,
            candidate_version=diff.candidate_version,
            diff_data=diff.diff_data,
            trace_id=diff.trace_id,
            created_at=diff.created_at,
        )

    @staticmethod
    def _shadow_diff_to_domain_model(
        record: NormalizationShadowDiffModel,
    ) -> NormalizationShadowDiffEntry:
        return NormalizationShadowDiffEntry(
            id=record.id,
            tenant_id=record.tenant_id,
            replica_record_id=record.replica_record_id,
            candidate_version=record.candidate_version,
            diff_data=record.diff_data,
            trace_id=record.trace_id,
            created_at=record.created_at,
        )

    async def record_rejection(self, rejection: NormalizationRejectionEntry) -> None:
        """Persist a normalization rejection entry."""
        self.session.add(self._to_orm_model(rejection))

    async def record_shadow_diff(self, diff: NormalizationShadowDiffEntry) -> None:
        """Persist a candidate mapper difference entry in shadow mode."""
        self.session.add(self._shadow_diff_to_orm_model(diff))

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[NormalizationRejectionEntry]:
        stmt = (
            select(NormalizationRejectionModel)
            .where(
                NormalizationRejectionModel.trace_id == trace_id,
                NormalizationRejectionModel.tenant_id == tenant_id,
            )
            .order_by(NormalizationRejectionModel.created_at.asc())
        )
        res = await self._session.execute(stmt)
        return [self._to_domain_model(r) for r in res.scalars().all()]
