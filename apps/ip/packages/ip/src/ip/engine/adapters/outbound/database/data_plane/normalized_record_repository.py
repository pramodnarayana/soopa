"""SQLAlchemy repository adapter for Layer 3 NormalizedRecord aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import normalized_record_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import NormalizedRecordModel
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.ports.outbound.canonical_reader_port import (
    CanonicalReaderRegistryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from seedwork.domain.types import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyNormalizedRecordRepository(
    TenantSqlAlchemyRepository, NormalizedRecordRepositoryPort
):
    """Repository persisting and retrieving NormalizedRecord aggregates with transactional outbox draining."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        reader_registry: CanonicalReaderRegistryPort | None = None,
    ) -> None:
        super().__init__(session)
        self._reader_registry = reader_registry

    @staticmethod
    def _to_domain_model(orm: NormalizedRecordModel) -> NormalizedRecord:
        return normalized_record_to_domain(orm)

    @staticmethod
    def _sanitize_for_json(val: object) -> JsonValue:
        if isinstance(val, Decimal):
            return float(val)
        if isinstance(val, dict):
            return {
                str(k): SqlAlchemyNormalizedRecordRepository._sanitize_for_json(v)
                for k, v in val.items()
            }
        if isinstance(val, list):
            return [SqlAlchemyNormalizedRecordRepository._sanitize_for_json(item) for item in val]
        if isinstance(val, (str, int, float, bool)) or val is None:
            return val
        return str(val)

    @staticmethod
    def _to_orm_model(domain: NormalizedRecord) -> NormalizedRecordModel:
        sanitized = SqlAlchemyNormalizedRecordRepository._sanitize_for_json(domain.canonical_data)
        canonical_dict = sanitized if isinstance(sanitized, dict) else {}
        return NormalizedRecordModel(
            id=domain.id,
            tenant_id=domain.tenant_id,
            trace_id=domain.trace_id,
            correlation_id=domain.correlation_id,
            parent_trace_id=domain.parent_trace_id,
            original_trace_id=domain.original_trace_id,
            replay_count=domain.replay_count,
            connection_id=domain.connection_id,
            canonical_type=str(domain.canonical_type),
            source_id=domain.source_id,
            canonical_data=canonical_dict,
            normalized_at=domain.normalized_at,
        )

    async def save(self, record: NormalizedRecord) -> None:
        orm = self._to_orm_model(record)
        self._session.add(orm)
        self._drain_trace_events(record)
        if record.replay_count > 0:
            self._drain_events(record, default_tenant_id=record.tenant_id)
        else:
            record.clear_domain_events()
        await self._session.flush()

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        stmt = select(NormalizedRecordModel).where(
            NormalizedRecordModel.id == record_id,
            NormalizedRecordModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is not None:
            return self._to_domain_model(orm)

        if self._reader_registry is not None:
            for reader in self._reader_registry.all_readers():
                found = await reader.get_by_id(
                    self._session,
                    tenant_id=tenant_id,
                    record_id=record_id,
                )
                if found is not None:
                    return found
        return None

    async def list_by_source(
        self,
        tenant_id: str,
        canonical_type: str,
        source_id: str,
        connection_id: str | None = None,
    ) -> Sequence[NormalizedRecord]:
        conditions = [
            NormalizedRecordModel.tenant_id == tenant_id,
            NormalizedRecordModel.canonical_type == str(canonical_type),
            NormalizedRecordModel.source_id == source_id,
        ]
        if connection_id is not None:
            conditions.append(NormalizedRecordModel.connection_id == connection_id)
        stmt = (
            select(NormalizedRecordModel)
            .where(*conditions)
            .order_by(NormalizedRecordModel.normalized_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        canonical_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        stmt = select(NormalizedRecordModel).where(NormalizedRecordModel.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(NormalizedRecordModel.connection_id == connection_id)
        if canonical_type is not None:
            stmt = stmt.where(NormalizedRecordModel.canonical_type == str(canonical_type))
        stmt = (
            stmt.order_by(
                NormalizedRecordModel.normalized_at.desc(),
                NormalizedRecordModel.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        records = [self._to_domain_model(orm) for orm in result.scalars().all()]
        if records:
            return records

        if self._reader_registry is not None:
            if canonical_type is not None:
                reader = self._reader_registry.get(canonical_type)
                if reader is not None:
                    return await reader.list_records(
                        self._session,
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        limit=limit,
                        offset=offset,
                    )
            else:
                domain_records: list[NormalizedRecord] = []
                fetch_window = min(offset + limit, 500)
                for reader in self._reader_registry.all_readers():
                    recs = await reader.list_records(
                        self._session,
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        limit=fetch_window,
                        offset=0,
                    )
                    domain_records.extend(recs)
                if domain_records:
                    epoch_min = datetime.min.replace(tzinfo=UTC)
                    domain_records.sort(
                        key=lambda r: (r.normalized_at or epoch_min, r.id),
                        reverse=True,
                    )
                    return domain_records[offset : offset + limit]
        return ()

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[NormalizedRecord]:
        stmt = (
            select(NormalizedRecordModel)
            .where(
                NormalizedRecordModel.trace_id == trace_id,
                NormalizedRecordModel.tenant_id == tenant_id,
            )
            .order_by(NormalizedRecordModel.normalized_at.asc())
        )
        result = await self._session.execute(stmt)
        records = [self._to_domain_model(orm) for orm in result.scalars().all()]
        if records:
            return records

        if self._reader_registry is not None:
            domain_records: list[NormalizedRecord] = []
            for reader in self._reader_registry.all_readers():
                domain_recs = await reader.get_by_trace_id(
                    self._session,
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                )
                domain_records.extend(domain_recs)
            if domain_records:
                epoch_min = datetime.min.replace(tzinfo=UTC)
                domain_records.sort(key=lambda r: (r.normalized_at or epoch_min, r.id))
                return domain_records
        return ()
