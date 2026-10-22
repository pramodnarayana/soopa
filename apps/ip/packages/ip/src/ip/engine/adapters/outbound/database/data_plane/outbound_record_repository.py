"""SQLAlchemy adapter for Layer 5 OutboundRecord repository."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import OutboundRecordModel
from ip.engine.domain.enums import OutboundDispatchStatus
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyOutboundRecordRepository(TenantSqlAlchemyRepository, OutboundRecordRepositoryPort):
    """Repository persisting and retrieving OutboundRecord audit entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: OutboundRecordModel) -> OutboundRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate."""
        return OutboundRecord(
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
            target_url=orm.target_url,
            http_method=orm.http_method,
            request_headers=dict(orm.request_headers),
            request_body=dict(orm.request_body) if orm.request_body is not None else None,
            request_s3_key=orm.request_s3_key,
            request_size_bytes=orm.request_size_bytes,
            request_sha256=orm.request_sha256,
            status=OutboundDispatchStatus(orm.status),
            response_status_code=orm.response_status_code,
            response_headers=dict(orm.response_headers)
            if orm.response_headers is not None
            else None,
            response_body=dict(orm.response_body) if orm.response_body is not None else None,
            response_s3_key=orm.response_s3_key,
            duration_ms=orm.duration_ms,
            attempt_number=orm.attempt_number,
            error_message=orm.error_message,
            sent_at=orm.sent_at,
        )

    @staticmethod
    def _to_orm_model(domain: OutboundRecord) -> OutboundRecordModel:
        """Strict type-safe Data Mapper from Domain Aggregate to ORM model."""
        return OutboundRecordModel(
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
            target_url=domain.target_url,
            http_method=domain.http_method,
            request_headers=domain.request_headers,
            request_body=domain.request_body,
            request_s3_key=domain.request_s3_key,
            request_size_bytes=domain.request_size_bytes,
            request_sha256=domain.request_sha256,
            status=domain.status.value,
            response_status_code=domain.response_status_code,
            response_headers=domain.response_headers,
            response_body=domain.response_body,
            response_s3_key=domain.response_s3_key,
            duration_ms=domain.duration_ms,
            attempt_number=domain.attempt_number,
            error_message=domain.error_message,
            sent_at=domain.sent_at,
        )

    async def save(self, record: OutboundRecord) -> None:
        orm = self._to_orm_model(record)
        await self._session.merge(orm)
        self._drain_trace_events(record)
        self._drain_events(record, default_tenant_id=record.tenant_id)
        await self._session.flush()

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        stmt = select(OutboundRecordModel).where(
            OutboundRecordModel.id == record_id,
            OutboundRecordModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str
    ) -> Sequence[OutboundRecord]:
        stmt = (
            select(OutboundRecordModel)
            .where(
                OutboundRecordModel.trace_id == trace_id,
                OutboundRecordModel.tenant_id == tenant_id,
            )
            .order_by(OutboundRecordModel.sent_at.asc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]
