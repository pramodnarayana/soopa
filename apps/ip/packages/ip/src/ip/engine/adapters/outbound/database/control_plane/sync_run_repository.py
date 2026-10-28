"""SQLAlchemy implementation of SyncRunRepositoryPort for the Control Plane."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import SyncRunRecord
from ip.engine.domain.enums import SyncRunKind, SyncRunStatus
from ip.engine.domain.models.sync_run import SyncRun
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemySyncRunRepository(GlobalSqlAlchemyRepository, SyncRunRepositoryPort):
    """SQLAlchemy repository adapter for persisting and retrieving SyncRun aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: SyncRunRecord) -> SyncRun:
        """Strict explicit data mapper from ORM record to Domain Aggregate Root."""
        return SyncRun(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream=record.stream,
            kind=SyncRunKind(record.kind),
            generation_id=record.generation_id,
            status=SyncRunStatus(record.status),
            start_checkpoint=record.start_checkpoint,
            end_checkpoint=record.end_checkpoint,
            pages_count=record.pages_count,
            records_count=record.records_count,
            bytes_count=record.bytes_count,
            retry_count=record.retry_count,
            error_code=record.error_code,
            error_message=record.error_message,
            trace_id=record.trace_id,
            started_at=record.started_at,
            finished_at=record.finished_at,
            created_at=record.created_at,
        )

    @staticmethod
    def _to_orm_model(domain: SyncRun) -> SyncRunRecord:
        """Strict explicit data mapper from Domain Aggregate Root to ORM model."""
        return SyncRunRecord(
            id=domain.id,
            tenant_id=domain.tenant_id,
            connection_id=domain.connection_id,
            stream=domain.stream,
            kind=domain.kind.value,
            generation_id=domain.generation_id,
            status=domain.status.value,
            start_checkpoint=domain.start_checkpoint,
            end_checkpoint=domain.end_checkpoint,
            pages_count=domain.pages_count,
            records_count=domain.records_count,
            bytes_count=domain.bytes_count,
            retry_count=domain.retry_count,
            error_code=domain.error_code,
            error_message=domain.error_message,
            trace_id=domain.trace_id,
            started_at=domain.started_at,
            finished_at=domain.finished_at,
            created_at=domain.created_at,
        )

    @staticmethod
    def _update_record_from_domain(record: SyncRunRecord, domain: SyncRun) -> None:
        """Strict explicit data mapper updating ORM record fields from Domain Aggregate."""
        record.status = domain.status.value
        record.start_checkpoint = domain.start_checkpoint
        record.end_checkpoint = domain.end_checkpoint
        record.pages_count = domain.pages_count
        record.records_count = domain.records_count
        record.bytes_count = domain.bytes_count
        record.retry_count = domain.retry_count
        record.error_code = domain.error_code
        record.error_message = domain.error_message
        record.started_at = domain.started_at
        record.finished_at = domain.finished_at

    async def get_by_id(self, run_id: str, tenant_id: str) -> SyncRun | None:
        stmt = select(SyncRunRecord).where(
            SyncRunRecord.id == run_id,
            SyncRunRecord.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_active_run(
        self,
        connection_id: str,
        stream: str,
        tenant_id: str | None = None,
        for_update: bool = False,
    ) -> SyncRun | None:
        active_statuses = (SyncRunStatus.PENDING.value, SyncRunStatus.RUNNING.value)
        stmt = select(SyncRunRecord).where(
            SyncRunRecord.connection_id == connection_id,
            SyncRunRecord.stream == stream,
            SyncRunRecord.status.in_(active_statuses),
        )
        if tenant_id is not None:
            stmt = stmt.where(SyncRunRecord.tenant_id == tenant_id)
        if for_update:
            stmt = stmt.with_for_update()
        stmt = stmt.limit(1)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_latest_generation_id(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> int:
        stmt = (
            select(SyncRunRecord.generation_id)
            .where(
                SyncRunRecord.tenant_id == tenant_id,
                SyncRunRecord.connection_id == connection_id,
                SyncRunRecord.stream == stream,
            )
            .order_by(desc(SyncRunRecord.generation_id))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        latest = result.scalar_one_or_none()
        return int(latest) if latest is not None else 1

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
        limit: int = 50,
    ) -> Sequence[SyncRun]:
        stmt = (
            select(SyncRunRecord)
            .where(
                SyncRunRecord.tenant_id == tenant_id,
                SyncRunRecord.connection_id == connection_id,
            )
            .order_by(desc(SyncRunRecord.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(rec) for rec in result.scalars().all()]

    async def save(self, run: SyncRun) -> None:
        existing = await self._session.get(SyncRunRecord, run.id)
        if existing is not None:
            self._update_record_from_domain(existing, run)
        else:
            orm = self._to_orm_model(run)
            self._session.add(orm)

        self._drain_events(run, default_tenant_id=run.tenant_id)
        await self._session.flush()
