"""SQLAlchemy 2.0 ORM adapter for `config_sync.config_changelog` with atomic PostgreSQL NOTIFY."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import structlog
from database.config_changelog import record_config_changelog_entry
from database.models.config_sync import ConfigChangelogEntry
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_sync.domain.checksum import compute_payload_checksum
from config_sync.domain.dtos import ConfigDeltaEvent
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncChannel
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort

logger = structlog.get_logger(__name__)

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
WILDCARD_TENANT_ID = "*"


class SqlAlchemyConfigChangelogRepository(ConfigChangelogRepositoryPort):
    """Durable PostgreSQL append-only changelog driving Dynamic Watch catch-up & multi-pod NOTIFY."""

    _CLEANUP_CHUNK_SIZE: int = 1000

    def __init__(
        self,
        session_factory: SessionScopeFactory,
        *,
        notify_channel: str = ConfigSyncChannel.CONFIG_CHANGELOG_NOTIFY.value,
        shared_tenant_ids: tuple[str, ...] = (WILDCARD_TENANT_ID,),
    ) -> None:
        self._session_scope = session_factory
        self._notify_channel = notify_channel
        self._shared_tenant_ids = shared_tenant_ids

    @staticmethod
    def _to_delta_event(row: ConfigChangelogEntry) -> ConfigDeltaEvent:
        """Explicit Data Mapper from ORM `ConfigChangelogEntry` to domain `ConfigDeltaEvent`."""
        return ConfigDeltaEvent(
            event_id=row.event_id,
            app_id=row.app_id,
            tenant_id=row.tenant_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            action=ConfigChangeAction(row.action),
            version=int(row.version),
            checksum=row.checksum,
            payload=dict(row.payload),
        )

    async def append_change_in_session(
        self,
        session: AsyncSession,
        *,
        app_id: str,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        action: ConfigChangeAction,
        payload: JsonDict,
        event_id: str | None = None,
    ) -> ConfigDeltaEvent:
        """Appends a changelog row and schedules `pg_notify` inside the caller's active ACID transaction."""
        resolved_event_id = event_id or generate_id(SystemIdPrefix.GENERIC)
        checksum = compute_payload_checksum(payload)
        entry = await record_config_changelog_entry(
            session,
            event_id=resolved_event_id,
            app_id=app_id,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action.value,
            checksum=checksum,
            payload=dict(payload),
            notify_channel=self._notify_channel,
        )
        return self._to_delta_event(entry)

    async def append_change(
        self,
        *,
        app_id: str,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        action: ConfigChangeAction,
        payload: JsonDict,
        event_id: str | None = None,
    ) -> ConfigDeltaEvent:
        async with self._session_scope() as session:
            delta = await self.append_change_in_session(
                session,
                app_id=app_id,
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                payload=payload,
                event_id=event_id,
            )
            await session.commit()

        logger.info(
            "config_changelog_appended",
            app_id=app_id,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action.value,
            version=delta.version,
        )
        return delta

    async def get_latest_version(self, *, app_id: str, tenant_id: str) -> int:
        c = ConfigChangelogEntry
        tenant_scope = (tenant_id, *self._shared_tenant_ids)
        async with self._session_scope() as session:
            stmt = select(func.coalesce(func.max(c.version), 0)).where(
                c.app_id == app_id,
                or_(c.tenant_id == tenant_id, c.tenant_id.in_(tenant_scope)),
            )
            res = await session.execute(stmt)
            return int(res.scalar_one())

    async def get_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_version: int,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        c = ConfigChangelogEntry
        tenant_scope = (tenant_id, *self._shared_tenant_ids)
        async with self._session_scope() as session:
            stmt = (
                select(c)
                .where(
                    c.app_id == app_id,
                    c.tenant_id.in_(tenant_scope),
                    c.version > since_version,
                )
                .order_by(c.version.asc())
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).scalars().all())
        return [self._to_delta_event(row) for row in rows]

    async def get_entry_by_version(self, *, version: int) -> ConfigDeltaEvent | None:
        c = ConfigChangelogEntry
        async with self._session_scope() as session:
            row = (
                await session.execute(select(c).where(c.version == version))
            ).scalar_one_or_none()
            return self._to_delta_event(row) if row is not None else None

    async def get_entries_after_version(
        self,
        *,
        since_version: int,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        c = ConfigChangelogEntry
        async with self._session_scope() as session:
            stmt = select(c).where(c.version > since_version).order_by(c.version.asc()).limit(limit)
            rows = list((await session.execute(stmt)).scalars().all())
        return [self._to_delta_event(row) for row in rows]

    async def cleanup_old_entries(self, *, retention_days: int = 30) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        total_deleted = 0
        c = ConfigChangelogEntry
        while True:
            async with self._session_scope() as session:
                delete_cte = (
                    select(c.version)
                    .where(c.created_at < cutoff)
                    .limit(self._CLEANUP_CHUNK_SIZE)
                    .with_for_update(skip_locked=True)
                    .cte("config_changelog_rows_to_delete")
                )
                stmt = delete(c).where(c.version == delete_cte.c.version).returning(c.version)
                deleted = len((await session.execute(stmt)).scalars().all())
                await session.commit()
            total_deleted += deleted
            if deleted < self._CLEANUP_CHUNK_SIZE:
                break
            await asyncio.sleep(0.1)

        logger.info(
            "config_changelog_cleanup_completed",
            retention_days=retention_days,
            deleted_count=total_deleted,
        )
        return total_deleted


__all__ = ["WILDCARD_TENANT_ID", "SessionScopeFactory", "SqlAlchemyConfigChangelogRepository"]
