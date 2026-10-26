"""SQLAlchemy adapter for Layer 5 OutboundRecord repository."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import outbound_record_to_domain
from ip.engine.adapters.outbound.database.data_plane.payload_hydration import (
    hydrate_s3_json_payload,
)
from ip.engine.adapters.outbound.database.models.data_plane import OutboundRecordModel
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyOutboundRecordRepository(TenantSqlAlchemyRepository, OutboundRecordRepositoryPort):
    """Repository persisting and retrieving OutboundRecord audit entities."""

    def __init__(
        self,
        session: AsyncSession,
        storage: TieredStoragePort | None = None,
    ) -> None:
        super().__init__(session)
        self._storage = storage

    @staticmethod
    def _to_domain_model(orm: OutboundRecordModel) -> OutboundRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate."""
        return outbound_record_to_domain(orm)

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
            operation=domain.operation,
            idempotency_key=domain.idempotency_key,
            external_record_id=domain.external_record_id,
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
            failure_category=domain.failure_category,
            retry_after_seconds=domain.retry_after_seconds,
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
        stmt = (
            select(OutboundRecordModel)
            .where(
                OutboundRecordModel.id == record_id,
                OutboundRecordModel.tenant_id == tenant_id,
            )
            .order_by(OutboundRecordModel.sent_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
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
        records = [self._to_domain_model(orm) for orm in result.scalars().all()]
        if hydrate_payloads and self._storage is not None:
            for rec in records:
                if rec.request_s3_key:
                    rec.request_body = await hydrate_s3_json_payload(
                        self._storage,
                        s3_key=rec.request_s3_key,
                        inline_body=rec.request_body,
                        size_bytes=rec.request_size_bytes,
                        sha256=rec.request_sha256,
                    )
                if rec.response_s3_key:
                    rec.response_body = await hydrate_s3_json_payload(
                        self._storage,
                        s3_key=rec.response_s3_key,
                        inline_body=rec.response_body,
                    )
        return records

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None:
        stmt = (
            select(OutboundRecordModel)
            .where(
                OutboundRecordModel.tenant_id == tenant_id,
                OutboundRecordModel.connection_id == connection_id,
                OutboundRecordModel.idempotency_key == idempotency_key,
            )
            .order_by(OutboundRecordModel.sent_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)
