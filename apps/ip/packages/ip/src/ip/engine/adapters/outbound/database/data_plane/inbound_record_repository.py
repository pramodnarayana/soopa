"""SQLAlchemy adapter for Layer 1 InboundRecord repository."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import InboundRecordModel
from ip.engine.domain.enums import IngestionMode
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyInboundRecordRepository(TenantSqlAlchemyRepository, InboundRecordRepositoryPort):
    """Repository persisting and retrieving InboundRecord audit entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: InboundRecordModel) -> InboundRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate."""
        return InboundRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            connection_id=orm.connection_id,
            app_id=orm.app_id,
            stream_name=orm.stream_name,
            ingestion_mode=IngestionMode(orm.ingestion_mode),
            sync_run_id=orm.sync_run_id,
            generation_id=orm.generation_id,
            external_event_id=orm.external_event_id,
            request_headers=dict(orm.request_headers),
            request_body=dict(orm.request_body) if orm.request_body is not None else None,
            request_s3_key=orm.request_s3_key,
            request_size_bytes=orm.request_size_bytes,
            request_sha256=orm.request_sha256,
            response_status_code=orm.response_status_code,
            response_headers=dict(orm.response_headers)
            if orm.response_headers is not None
            else None,
            response_body=dict(orm.response_body) if orm.response_body is not None else None,
            response_s3_key=orm.response_s3_key,
            duration_ms=orm.duration_ms,
            received_at=orm.received_at,
        )

    @staticmethod
    def _to_orm_model(domain: InboundRecord) -> InboundRecordModel:
        """Strict type-safe Data Mapper from Domain Aggregate to ORM model."""
        return InboundRecordModel(
            id=domain.id,
            tenant_id=domain.tenant_id,
            trace_id=domain.trace_id,
            correlation_id=domain.correlation_id,
            parent_trace_id=domain.parent_trace_id,
            original_trace_id=domain.original_trace_id,
            replay_count=domain.replay_count,
            connection_id=domain.connection_id,
            app_id=domain.app_id,
            stream_name=domain.stream_name,
            ingestion_mode=domain.ingestion_mode.value,
            sync_run_id=domain.sync_run_id,
            generation_id=domain.generation_id,
            external_event_id=domain.external_event_id,
            request_headers=domain.request_headers,
            request_body=domain.request_body,
            request_s3_key=domain.request_s3_key,
            request_size_bytes=domain.request_size_bytes,
            request_sha256=domain.request_sha256,
            response_status_code=domain.response_status_code,
            response_headers=domain.response_headers,
            response_body=domain.response_body,
            response_s3_key=domain.response_s3_key,
            duration_ms=domain.duration_ms,
            received_at=domain.received_at,
        )

    async def save(self, record: InboundRecord) -> None:
        orm = self._to_orm_model(record)
        self._session.add(orm)
        self._drain_trace_events(record)
        self._drain_events(record, default_tenant_id=record.tenant_id)
        await self._session.flush()

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        stmt = select(InboundRecordModel).where(
            InboundRecordModel.id == record_id,
            InboundRecordModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
        stmt = (
            select(InboundRecordModel)
            .where(
                InboundRecordModel.trace_id == trace_id,
                InboundRecordModel.tenant_id == tenant_id,
            )
            .order_by(InboundRecordModel.received_at.asc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]

    async def get_by_external_event_id(
        self,
        tenant_id: str,
        connection_id: str,
        external_event_id: str,
    ) -> InboundRecord | None:
        stmt = select(InboundRecordModel).where(
            InboundRecordModel.tenant_id == tenant_id,
            InboundRecordModel.connection_id == connection_id,
            InboundRecordModel.external_event_id == external_event_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)
