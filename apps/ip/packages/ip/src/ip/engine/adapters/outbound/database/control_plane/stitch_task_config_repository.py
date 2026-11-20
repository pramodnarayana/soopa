"""SQLAlchemy repository adapter for StitchTaskConfig aggregates in Control Plane (`ip.stitch_task_configs`)."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import StitchTaskConfigRecord
from ip.engine.domain.stitch.stitch_task_config import StitchTaskConfig
from ip.engine.ports.outbound.stitch_task_config_repository_port import (
    StitchTaskConfigRepositoryPort,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyStitchTaskConfigRepository(
    GlobalSqlAlchemyRepository, StitchTaskConfigRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of StitchTaskConfigRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: StitchTaskConfigRecord) -> StitchTaskConfig:
        return StitchTaskConfig(
            id=record.id,
            tenant_id=record.tenant_id,
            stitch_id=record.stitch_id,
            node_key=record.node_key,
            timeout_seconds=record.timeout_seconds,
            heartbeat_interval_seconds=record.heartbeat_interval_seconds,
            max_attempts=record.max_attempts,
            initial_delay_seconds=record.initial_delay_seconds,
            backoff_multiplier=record.backoff_multiplier,
            max_delay_seconds=record.max_delay_seconds,
            queue_name=record.queue_name,
            max_in_flight_tasks=record.max_in_flight_tasks,
            failure_disposition=record.failure_disposition,
            quarantine_stream_name=record.quarantine_stream_name,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )

    @staticmethod
    def _to_orm_model(
        config: StitchTaskConfig, created_at: datetime, updated_at: datetime
    ) -> StitchTaskConfigRecord:
        return StitchTaskConfigRecord(
            id=config.id,
            tenant_id=config.tenant_id,
            stitch_id=config.stitch_id,
            node_key=config.node_key,
            timeout_seconds=config.timeout_seconds,
            heartbeat_interval_seconds=config.heartbeat_interval_seconds,
            max_attempts=config.max_attempts,
            initial_delay_seconds=config.initial_delay_seconds,
            backoff_multiplier=config.backoff_multiplier,
            max_delay_seconds=config.max_delay_seconds,
            queue_name=config.queue_name,
            max_in_flight_tasks=config.max_in_flight_tasks,
            failure_disposition=config.failure_disposition,
            quarantine_stream_name=config.quarantine_stream_name,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: StitchTaskConfigRecord,
        config: StitchTaskConfig,
        updated_at: datetime,
    ) -> None:
        record.timeout_seconds = config.timeout_seconds
        record.heartbeat_interval_seconds = config.heartbeat_interval_seconds
        record.max_attempts = config.max_attempts
        record.initial_delay_seconds = config.initial_delay_seconds
        record.backoff_multiplier = config.backoff_multiplier
        record.max_delay_seconds = config.max_delay_seconds
        record.queue_name = config.queue_name
        record.max_in_flight_tasks = config.max_in_flight_tasks
        record.failure_disposition = config.failure_disposition
        record.quarantine_stream_name = config.quarantine_stream_name
        record.updated_at = updated_at

    async def get_by_node(
        self, tenant_id: str, stitch_id: str, node_key: str
    ) -> StitchTaskConfig | None:
        stmt = select(StitchTaskConfigRecord).where(
            StitchTaskConfigRecord.tenant_id == tenant_id,
            StitchTaskConfigRecord.stitch_id == stitch_id,
            StitchTaskConfigRecord.node_key == node_key,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return self._to_domain_model(record) if record is not None else None

    async def list_by_stitch(self, tenant_id: str, stitch_id: str) -> list[StitchTaskConfig]:
        stmt = (
            select(StitchTaskConfigRecord)
            .where(
                StitchTaskConfigRecord.tenant_id == tenant_id,
                StitchTaskConfigRecord.stitch_id == stitch_id,
            )
            .order_by(StitchTaskConfigRecord.node_key.asc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def save(self, config: StitchTaskConfig) -> None:
        now = datetime.now(UTC)
        stmt = select(StitchTaskConfigRecord).where(
            StitchTaskConfigRecord.tenant_id == config.tenant_id,
            StitchTaskConfigRecord.stitch_id == config.stitch_id,
            StitchTaskConfigRecord.node_key == config.node_key,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(config, now, now))
        else:
            self._update_record_from_domain(record, config, now)

        self._drain_events(config, default_tenant_id=config.tenant_id)

    async def delete(
        self,
        tenant_id: str,
        stitch_id: str,
        node_key: str,
        config: StitchTaskConfig | None = None,
    ) -> bool:
        if config is not None:
            self._drain_events(config, default_tenant_id=tenant_id)

        stmt = (
            delete(StitchTaskConfigRecord)
            .where(
                StitchTaskConfigRecord.tenant_id == tenant_id,
                StitchTaskConfigRecord.stitch_id == stitch_id,
                StitchTaskConfigRecord.node_key == node_key,
            )
            .returning(StitchTaskConfigRecord.id)
        )
        result = await self.session.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        return deleted_id is not None


__all__ = ["SqlAlchemyStitchTaskConfigRepository"]
