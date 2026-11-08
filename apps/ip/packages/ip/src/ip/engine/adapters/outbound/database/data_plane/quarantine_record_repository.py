"""SQLAlchemy Repository Adapter for Layer-5 QuarantineRecords (`public.quarantine_records`)."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import (
    quarantine_record_to_domain,
)
from ip.engine.adapters.outbound.database.models.data_plane import QuarantineRecordModel
from ip.engine.domain.dispatch.quarantine_record import QuarantineRecord
from ip.engine.ports.outbound.quarantine_record_repository_port import (
    QuarantineRecordRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyQuarantineRecordRepository(
    TenantSqlAlchemyRepository,
    QuarantineRecordRepositoryPort,
):
    """Concrete SQLAlchemy repository persisting terminally failed outbound dispatches."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: QuarantineRecordModel) -> QuarantineRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Value Object."""
        return quarantine_record_to_domain(orm)

    async def save(self, record: QuarantineRecord) -> None:
        stmt = (
            pg_insert(QuarantineRecordModel)
            .values(
                id=record.id,
                tenant_id=record.tenant_id,
                connection_id=record.connection_id,
                outbound_record_id=record.outbound_record_id,
                stream_name=record.stream_name,
                idempotency_key=record.idempotency_key,
                trace_id=record.trace_id,
                correlation_id=record.correlation_id,
                failure_category=record.failure_category,
                error_code=record.error_code,
                error_message=record.error_message,
                response_status_code=record.response_status_code,
                attempt_count=record.attempt_count,
                request_body=record.request_body,
                request_s3_key=record.request_s3_key,
                response_body=record.response_body,
                response_s3_key=record.response_s3_key,
                quarantined_at=record.quarantined_at,
            )
            .on_conflict_do_update(
                index_elements=[QuarantineRecordModel.id],
                set_={
                    "failure_category": record.failure_category,
                    "error_code": record.error_code,
                    "error_message": record.error_message,
                    "response_status_code": record.response_status_code,
                    "attempt_count": record.attempt_count,
                    "response_body": record.response_body,
                    "response_s3_key": record.response_s3_key,
                    "quarantined_at": record.quarantined_at,
                },
            )
        )
        await self._session.execute(stmt)

    async def get_by_id(self, record_id: str, tenant_id: str) -> QuarantineRecord | None:
        stmt = select(QuarantineRecordModel).where(
            QuarantineRecordModel.id == record_id,
            QuarantineRecordModel.tenant_id == tenant_id,
        )
        res = await self._session.execute(stmt)
        row = res.scalar_one_or_none()
        return self._to_domain_model(row) if row is not None else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[QuarantineRecord]:
        stmt = select(QuarantineRecordModel).where(QuarantineRecordModel.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(QuarantineRecordModel.connection_id == connection_id)
        stmt = (
            stmt.order_by(QuarantineRecordModel.quarantined_at.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        res = await self._session.execute(stmt)
        return [self._to_domain_model(row) for row in res.scalars().all()]


__all__ = ["SqlAlchemyQuarantineRecordRepository"]
