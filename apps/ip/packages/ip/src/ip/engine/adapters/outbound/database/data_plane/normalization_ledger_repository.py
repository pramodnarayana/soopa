"""SQLAlchemy repository adapter for NormalizationLedger aggregates on tenant shards."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import NormalizationLedgerModel
from ip.engine.domain.enums import NormalizationOutcome
from ip.engine.domain.normalization import NormalizationLedgerEntry
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyNormalizationLedgerRepository(
    TenantSqlAlchemyRepository, NormalizationLedgerRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of NormalizationLedgerRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: NormalizationLedgerModel) -> NormalizationLedgerEntry:
        refs: list[tuple[str, str]] = []
        if isinstance(record.produced_canonical_refs, list):
            for item in record.produced_canonical_refs:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    refs.append((str(item[0]), str(item[1])))
        return NormalizationLedgerEntry(
            id=record.id,
            tenant_id=record.tenant_id,
            replica_record_id=record.replica_record_id,
            replica_version=record.replica_version,
            transformation_id=record.transformation_id,
            transformation_version=record.transformation_version,
            produced_canonical_refs=tuple(refs),
            outcome=NormalizationOutcome(record.outcome),
            trace_id=record.trace_id,
            correlation_id=record.correlation_id,
            created_at=record.created_at,
        )

    @staticmethod
    def _to_orm_model(entry: NormalizationLedgerEntry) -> NormalizationLedgerModel:
        raw_refs = [[ref[0], ref[1]] for ref in entry.produced_canonical_refs]
        return NormalizationLedgerModel(
            id=entry.id,
            tenant_id=entry.tenant_id,
            replica_record_id=entry.replica_record_id,
            replica_version=entry.replica_version,
            transformation_id=entry.transformation_id,
            transformation_version=entry.transformation_version,
            produced_canonical_refs=raw_refs,
            outcome=entry.outcome.value,
            trace_id=entry.trace_id,
            correlation_id=entry.correlation_id,
            created_at=entry.created_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: NormalizationLedgerModel, entry: NormalizationLedgerEntry
    ) -> None:
        record.replica_version = entry.replica_version
        record.produced_canonical_refs = [[ref[0], ref[1]] for ref in entry.produced_canonical_refs]
        record.outcome = entry.outcome.value
        record.trace_id = entry.trace_id
        record.correlation_id = entry.correlation_id
        record.created_at = entry.created_at

    async def get_latest_version(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> int | None:
        """Retrieve highest processed replica version for this replica and transformer version."""
        stmt = (
            select(NormalizationLedgerModel.replica_version)
            .where(
                NormalizationLedgerModel.tenant_id == tenant_id,
                NormalizationLedgerModel.replica_record_id == replica_record_id,
                NormalizationLedgerModel.transformation_id == transformation_id,
                NormalizationLedgerModel.transformation_version == transformation_version,
            )
            .order_by(NormalizationLedgerModel.replica_version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> tuple[tuple[str, str], ...]:
        """Retrieve canonical references produced by the most recent normalization run."""
        stmt = (
            select(NormalizationLedgerModel)
            .where(
                NormalizationLedgerModel.tenant_id == tenant_id,
                NormalizationLedgerModel.replica_record_id == replica_record_id,
                NormalizationLedgerModel.transformation_id == transformation_id,
                NormalizationLedgerModel.transformation_version == transformation_version,
            )
            .order_by(NormalizationLedgerModel.replica_version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return ()
        domain = self._to_domain_model(record)
        return domain.produced_canonical_refs

    async def get_latest_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
    ) -> tuple[tuple[str, str], ...]:
        """Retrieve canonical references produced by the most recent normalization run across all transformation versions."""
        stmt = (
            select(NormalizationLedgerModel)
            .where(
                NormalizationLedgerModel.tenant_id == tenant_id,
                NormalizationLedgerModel.replica_record_id == replica_record_id,
                NormalizationLedgerModel.transformation_id == transformation_id,
                NormalizationLedgerModel.outcome.in_(
                    [NormalizationOutcome.NORMALIZED.value, NormalizationOutcome.TOMBSTONED.value]
                ),
            )
            .order_by(
                NormalizationLedgerModel.created_at.desc(),
                NormalizationLedgerModel.replica_version.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return ()
        domain = self._to_domain_model(record)
        return domain.produced_canonical_refs

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        """Insert or update a normalization ledger entry."""
        stmt = select(NormalizationLedgerModel).where(
            NormalizationLedgerModel.tenant_id == entry.tenant_id,
            NormalizationLedgerModel.replica_record_id == entry.replica_record_id,
            NormalizationLedgerModel.transformation_id == entry.transformation_id,
            NormalizationLedgerModel.transformation_version == entry.transformation_version,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(entry))
        else:
            self._update_record_from_domain(record, entry)
