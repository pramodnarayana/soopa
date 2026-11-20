"""SQLAlchemy repository adapter for ConnectionPolicy aggregates in Control Plane (`ip.connection_policies`)."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionPolicyRecord
from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyConnectionPolicyRepository(
    GlobalSqlAlchemyRepository, ConnectionPolicyRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of ConnectionPolicyRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: ConnectionPolicyRecord) -> ConnectionPolicy:
        return ConnectionPolicy(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            max_query_window_days=record.max_query_window_days,
            max_query_window_hours=record.max_query_window_hours,
            min_query_window_minutes=record.min_query_window_minutes,
            max_entities_per_call=record.max_entities_per_call,
            max_records_per_batch=record.max_records_per_batch,
            supports_wildcard_queries=record.supports_wildcard_queries,
            max_concurrency=record.max_concurrency,
            rate_limit_rpm=record.rate_limit_rpm,
            cooldown_seconds_between_calls=record.cooldown_seconds_between_calls,
            blackout_cron_schedule=record.blackout_cron_schedule,
            blackout_duration_minutes=record.blackout_duration_minutes,
            vendor_quirks=dict(record.vendor_quirks or {}),
            is_enabled=record.is_enabled,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )

    @staticmethod
    def _to_orm_model(
        policy: ConnectionPolicy, created_at: datetime, updated_at: datetime
    ) -> ConnectionPolicyRecord:
        return ConnectionPolicyRecord(
            id=policy.id,
            tenant_id=policy.tenant_id,
            connection_id=policy.connection_id,
            max_query_window_days=policy.max_query_window_days,
            max_query_window_hours=policy.max_query_window_hours,
            min_query_window_minutes=policy.min_query_window_minutes,
            max_entities_per_call=policy.max_entities_per_call,
            max_records_per_batch=policy.max_records_per_batch,
            supports_wildcard_queries=policy.supports_wildcard_queries,
            max_concurrency=policy.max_concurrency,
            rate_limit_rpm=policy.rate_limit_rpm,
            cooldown_seconds_between_calls=policy.cooldown_seconds_between_calls,
            blackout_cron_schedule=policy.blackout_cron_schedule,
            blackout_duration_minutes=policy.blackout_duration_minutes,
            vendor_quirks=dict(policy.vendor_quirks),
            is_enabled=policy.is_enabled,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: ConnectionPolicyRecord,
        policy: ConnectionPolicy,
        updated_at: datetime,
    ) -> None:
        record.max_query_window_days = policy.max_query_window_days
        record.max_query_window_hours = policy.max_query_window_hours
        record.min_query_window_minutes = policy.min_query_window_minutes
        record.max_entities_per_call = policy.max_entities_per_call
        record.max_records_per_batch = policy.max_records_per_batch
        record.supports_wildcard_queries = policy.supports_wildcard_queries
        record.max_concurrency = policy.max_concurrency
        record.rate_limit_rpm = policy.rate_limit_rpm
        record.cooldown_seconds_between_calls = policy.cooldown_seconds_between_calls
        record.blackout_cron_schedule = policy.blackout_cron_schedule
        record.blackout_duration_minutes = policy.blackout_duration_minutes
        record.vendor_quirks = dict(policy.vendor_quirks)
        record.is_enabled = policy.is_enabled
        record.updated_at = updated_at

    async def get_by_connection_id(
        self, tenant_id: str, connection_id: str
    ) -> ConnectionPolicy | None:
        stmt = select(ConnectionPolicyRecord).where(
            ConnectionPolicyRecord.tenant_id == tenant_id,
            ConnectionPolicyRecord.connection_id == connection_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return self._to_domain_model(record) if record is not None else None

    async def get_by_id(self, tenant_id: str, policy_id: str) -> ConnectionPolicy | None:
        stmt = select(ConnectionPolicyRecord).where(
            ConnectionPolicyRecord.tenant_id == tenant_id,
            ConnectionPolicyRecord.id == policy_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return self._to_domain_model(record) if record is not None else None

    async def save(self, policy: ConnectionPolicy) -> None:
        now = datetime.now(UTC)
        stmt = select(ConnectionPolicyRecord).where(
            ConnectionPolicyRecord.tenant_id == policy.tenant_id,
            ConnectionPolicyRecord.connection_id == policy.connection_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(policy, now, now))
        else:
            self._update_record_from_domain(record, policy, now)

        self._drain_events(policy, default_tenant_id=policy.tenant_id)

    async def delete(
        self,
        tenant_id: str,
        connection_id: str,
        policy: ConnectionPolicy | None = None,
    ) -> bool:
        if policy is not None:
            self._drain_events(policy, default_tenant_id=tenant_id)

        stmt = (
            delete(ConnectionPolicyRecord)
            .where(
                ConnectionPolicyRecord.tenant_id == tenant_id,
                ConnectionPolicyRecord.connection_id == connection_id,
            )
            .returning(ConnectionPolicyRecord.id)
        )
        result = await self.session.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        return deleted_id is not None


__all__ = ["SqlAlchemyConnectionPolicyRepository"]
