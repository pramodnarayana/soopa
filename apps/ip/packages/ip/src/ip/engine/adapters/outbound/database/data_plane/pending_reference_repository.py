"""SQLAlchemy repository adapter for PendingReference tracking on tenant shards."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import PendingReferenceModel
from ip.engine.domain.enums import PendingReferenceStatus
from ip.engine.domain.normalization import PendingReferenceEntry
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyPendingReferenceRepository(
    TenantSqlAlchemyRepository, PendingReferenceRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of PendingReferenceRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(model: PendingReferenceModel) -> PendingReferenceEntry:
        return PendingReferenceEntry(
            id=model.id,
            tenant_id=model.tenant_id,
            source_connection_id=model.source_connection_id,
            target_canonical_type=model.target_canonical_type,
            target_source_id=model.target_source_id,
            referencing_canonical_type=model.referencing_canonical_type,
            referencing_source_id=model.referencing_source_id,
            referencing_field=model.referencing_field,
            status=PendingReferenceStatus(model.status),
            trace_id=model.trace_id,
            created_at=model.created_at,
            resolved_at=model.resolved_at,
        )

    @staticmethod
    def _to_orm_model(entry: PendingReferenceEntry) -> PendingReferenceModel:
        return PendingReferenceModel(
            id=entry.id,
            tenant_id=entry.tenant_id,
            source_connection_id=entry.source_connection_id,
            target_canonical_type=entry.target_canonical_type,
            target_source_id=entry.target_source_id,
            referencing_canonical_type=entry.referencing_canonical_type,
            referencing_source_id=entry.referencing_source_id,
            referencing_field=entry.referencing_field,
            status=entry.status.value,
            trace_id=entry.trace_id,
            created_at=entry.created_at,
            resolved_at=entry.resolved_at,
        )

    async def record_pending(self, entry: PendingReferenceEntry) -> None:
        """Record an unresolved reference waiting for its target canonical record."""
        self.session.add(self._to_orm_model(entry))

    async def resolve_pending_for_target(
        self,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> list[PendingReferenceEntry]:
        """Mark as resolved and return all pending references matching a newly arrived target."""
        stmt = select(PendingReferenceModel).where(
            PendingReferenceModel.tenant_id == tenant_id,
            PendingReferenceModel.source_connection_id == source_connection_id,
            PendingReferenceModel.target_canonical_type == target_canonical_type,
            PendingReferenceModel.target_source_id == target_source_id,
            PendingReferenceModel.status == PendingReferenceStatus.PENDING.value,
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        now = datetime.now(UTC)
        entries: list[PendingReferenceEntry] = []
        for r in records:
            r.status = PendingReferenceStatus.RESOLVED.value
            r.resolved_at = now
            entries.append(self._to_domain_model(r))
        return entries
