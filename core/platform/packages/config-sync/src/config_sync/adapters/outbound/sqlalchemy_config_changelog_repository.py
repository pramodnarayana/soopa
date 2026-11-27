"""SQLAlchemy 2.0 ORM adapter for `config_sync.config_changelog` with `xid8` MVCC visibility barrier."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import structlog
from database.config_changelog import (
    config_changelog_visibility_barrier,
    record_config_changelog_entry,
)
from database.models.config_sync import ConfigChangelogEntry
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from config_sync.domain.checksum import compute_payload_checksum
from config_sync.domain.dtos import (
    ChangelogVisibilityWatermark,
    ConfigCursor,
    ConfigDeltaEvent,
)
from config_sync.domain.enums import ConfigChangeAction
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort

logger = structlog.get_logger(__name__)

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlAlchemyConfigChangelogRepository(ConfigChangelogRepositoryPort):
    """Durable PostgreSQL append-only changelog driving linearizable `(txid, version)` tailing."""

    _CLEANUP_CHUNK_SIZE: int = 1000

    def __init__(
        self,
        session_factory: SessionScopeFactory,
        *,
        shared_tenant_ids: tuple[str, ...] = (),
    ) -> None:
        self._session_scope = session_factory
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
            txid=int(row.txid),
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
        """Appends a changelog row inside the caller's active ACID transaction (zero `AsyncQueueLock`)."""
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

    async def get_latest_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        c = ConfigChangelogEntry
        tenant_scope = tuple({tenant_id, *self._shared_tenant_ids})
        async with self._session_scope() as session:
            stmt = (
                select(c.txid, c.version)
                .where(
                    c.app_id == app_id,
                    c.tenant_id.in_(tenant_scope),
                    config_changelog_visibility_barrier(),
                )
                .order_by(c.txid.desc(), c.version.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                return ConfigCursor.zero()
            return ConfigCursor(txid=int(row[0]), version=int(row[1]))

    async def get_global_safe_cursor(self) -> ConfigCursor:
        c = ConfigChangelogEntry
        async with self._session_scope() as session:
            stmt = (
                select(c.txid, c.version)
                .where(config_changelog_visibility_barrier())
                .order_by(c.txid.desc(), c.version.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                return ConfigCursor.zero()
            return ConfigCursor(txid=int(row[0]), version=int(row[1]))

    async def get_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        c = ConfigChangelogEntry
        tenant_scope = tuple({tenant_id, *self._shared_tenant_ids})
        async with self._session_scope() as session:
            stmt = (
                select(c)
                .where(
                    c.app_id == app_id,
                    c.tenant_id.in_(tenant_scope),
                    tuple_(c.txid, c.version) > (since_cursor.txid, since_cursor.version),
                    config_changelog_visibility_barrier(),
                )
                .order_by(c.txid.asc(), c.version.asc())
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).scalars().all())
        return [self._to_delta_event(row) for row in rows]

    async def get_entries_after_cursor(
        self,
        *,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        c = ConfigChangelogEntry
        async with self._session_scope() as session:
            stmt = (
                select(c)
                .where(
                    tuple_(c.txid, c.version) > (since_cursor.txid, since_cursor.version),
                    config_changelog_visibility_barrier(),
                )
                .order_by(c.txid.asc(), c.version.asc())
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).scalars().all())
        return [self._to_delta_event(row) for row in rows]

    async def get_visibility_lag_metrics(self) -> ChangelogVisibilityWatermark:
        """O(log N) backward B-tree scans comparing visibility-safe head vs raw committed head."""
        c = ConfigChangelogEntry
        async with self._session_scope() as session:
            safe_row = (
                await session.execute(
                    select(c.txid, c.version)
                    .where(config_changelog_visibility_barrier())
                    .order_by(c.txid.desc(), c.version.desc())
                    .limit(1)
                )
            ).first()
            raw_row = (
                await session.execute(
                    select(c.txid, c.version).order_by(c.txid.desc(), c.version.desc()).limit(1)
                )
            ).first()
            safe_cursor = (
                ConfigCursor(txid=int(safe_row[0]), version=int(safe_row[1]))
                if safe_row is not None
                else ConfigCursor.zero()
            )
            raw_cursor = (
                ConfigCursor(txid=int(raw_row[0]), version=int(raw_row[1]))
                if raw_row is not None
                else ConfigCursor.zero()
            )
            return ChangelogVisibilityWatermark(
                safe_cursor=safe_cursor,
                raw_max_cursor=raw_cursor,
            )

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


__all__ = ["SessionScopeFactory", "SqlAlchemyConfigChangelogRepository"]
