"""Centralized SQLAlchemy helpers for atomic `config_sync.config_changelog` reads, writes, and `pg_notify`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.config_sync import ConfigChangelogEntry

DEFAULT_CONFIG_CHANGELOG_NOTIFY_CHANNEL = "config_sync_changelog"


async def record_config_changelog_entry(
    session: AsyncSession,
    *,
    event_id: str,
    app_id: str,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    checksum: str,
    payload: dict[str, object],
    notify_channel: str = DEFAULT_CONFIG_CHANGELOG_NOTIFY_CHANNEL,
) -> ConfigChangelogEntry:
    """Appends a `ConfigChangelogEntry` and emits a tiny pointer-only `pg_notify` in the caller's ACID transaction."""
    entry = ConfigChangelogEntry(
        event_id=event_id,
        app_id=app_id,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        checksum=checksum,
        payload=dict(payload),
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.flush()

    if isinstance(entry.version, int):
        notify_body = json.dumps(
            {
                "version": int(entry.version),
                "app_id": app_id,
                "tenant_id": tenant_id,
            },
            separators=(",", ":"),
        )
        await session.execute(select(func.pg_notify(notify_channel, notify_body)))

    return entry


async def get_latest_config_changelog_version_in_session(
    session: AsyncSession,
    *,
    app_id: str,
    tenant_id: str,
    shared_tenant_ids: Sequence[str] = ("*",),
) -> int:
    """Reads the highest changelog version visible to `(app_id, tenant_id)` within the caller's active transaction.

    Must be invoked inside the SAME transaction (BEFORE or alongside entity snapshot queries)
    so concurrent mutations committed during snapshot assembly are never silently skipped.
    """
    tenant_scope = tuple({tenant_id, *shared_tenant_ids})
    stmt = select(func.coalesce(func.max(ConfigChangelogEntry.version), 0)).where(
        ConfigChangelogEntry.app_id == app_id,
        ConfigChangelogEntry.tenant_id.in_(tenant_scope),
    )
    return int((await session.execute(stmt)).scalar_one())


__all__ = [
    "DEFAULT_CONFIG_CHANGELOG_NOTIFY_CHANNEL",
    "get_latest_config_changelog_version_in_session",
    "record_config_changelog_entry",
]
