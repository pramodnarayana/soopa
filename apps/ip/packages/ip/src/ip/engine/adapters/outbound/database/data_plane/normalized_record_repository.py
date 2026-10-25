"""SQLAlchemy repository adapter for Layer 3 NormalizedRecord aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import NormalizedRecordModel
from ip.engine.domain.models.normalized_record import NormalizedRecord
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

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: NormalizedRecordModel) -> NormalizedRecord:
        return NormalizedRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            connection_id=orm.connection_id,
            canonical_type=orm.canonical_type,
            source_id=orm.source_id,
            canonical_data=dict(orm.canonical_data),
            normalized_at=orm.normalized_at,
        )

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
        self._drain_events(record, default_tenant_id=record.tenant_id)
        await self._session.flush()

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        stmt = select(NormalizedRecordModel).where(
            NormalizedRecordModel.id == record_id,
            NormalizedRecordModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def list_by_source(
        self,
        tenant_id: str,
        canonical_type: str,
        source_id: str,
    ) -> Sequence[NormalizedRecord]:
        stmt = (
            select(NormalizedRecordModel)
            .where(
                NormalizedRecordModel.tenant_id == tenant_id,
                NormalizedRecordModel.canonical_type == str(canonical_type),
                NormalizedRecordModel.source_id == source_id,
            )
            .order_by(NormalizedRecordModel.normalized_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]
