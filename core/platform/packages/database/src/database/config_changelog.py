"""Centralized SQLAlchemy helpers for atomic, MVCC-linearizable `config_sync.config_changelog` reads & writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from seedwork.domain.types import JsonDict
from sqlalchemy import ColumnElement, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from database.models.config_sync import ConfigChangelogEntry

# Protects `global_db` `pg_snapshot_xmin` against hung OLTP write transactions stalling
# the `xid8` visibility horizon (10s idle-in-transaction, 30s statement timeout).
CONTROL_PLANE_OLTP_SERVER_SETTINGS: dict[str, str] = {
    "idle_in_transaction_session_timeout": "10000",
    "statement_timeout": "30000",
}


def config_changelog_visibility_barrier() -> ColumnElement[bool]:
    """PostgreSQL `xid8` MVCC visibility barrier preventing out-of-order commit loss.

    Rows whose inserting transaction `txid` is strictly older than the lowest active uncommitted
    write transaction (`pg_snapshot_xmin(pg_current_snapshot())`) are guaranteed committed in
    linearizable `(txid, version)` order. The `txid = pg_current_xact_id_if_assigned()` branch
    evaluates to NULL (falsy) for all read-only queries while preserving read-your-own-writes
    inside the caller's own active transaction (such as SAVEPOINT integration tests).
    """
    return or_(
        ConfigChangelogEntry.txid < func.pg_snapshot_xmin(func.pg_current_snapshot()),
        ConfigChangelogEntry.txid == func.pg_current_xact_id_if_assigned(),
    )


async def ensure_repeatable_read_snapshot(session: AsyncSession) -> None:
    """Enforces lock-free `REPEATABLE READ READ ONLY` snapshot isolation on fresh DB transactions.

    Prevents torn reads across multi-table topological snapshots (e.g. parent Partner vs child
    Partnership FK layers). Skips safely when bound directly to an outer `AsyncConnection`
    already inside an active SAVEPOINT test harness transaction (PostgreSQL forbids changing
    isolation level inside subtransactions).
    """
    if isinstance(session.bind, AsyncConnection) or session.in_transaction():
        return
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))


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
    payload: JsonDict,
) -> ConfigChangelogEntry:
    """Appends a `ConfigChangelogEntry` inside the caller's ACID transaction (zero `AsyncQueueLock`)."""
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
    return entry


async def get_latest_config_changelog_cursor_in_session(
    session: AsyncSession,
    *,
    app_id: str,
    tenant_id: str,
    shared_tenant_ids: Sequence[str] = (),
) -> tuple[int, int]:
    """Reads the highest visibility-safe `(txid, version)` cursor for `(app_id, tenant_id)` in-session.

    Must be invoked inside the SAME `REPEATABLE READ` transaction alongside entity snapshot queries
    so any concurrent in-flight write transaction (`txid >= pg_snapshot_xmin`) is replayed cleanly
    when the worker resumes its Dynamic Watch stream from the returned `(txid, version)` cursor.
    """
    tenant_scope = tuple({tenant_id, *shared_tenant_ids})
    stmt = (
        select(ConfigChangelogEntry.txid, ConfigChangelogEntry.version)
        .where(
            ConfigChangelogEntry.app_id == app_id,
            ConfigChangelogEntry.tenant_id.in_(tenant_scope),
            config_changelog_visibility_barrier(),
        )
        .order_by(ConfigChangelogEntry.txid.desc(), ConfigChangelogEntry.version.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return (0, 0)
    return (int(row[0]), int(row[1]))


__all__ = [
    "CONTROL_PLANE_OLTP_SERVER_SETTINGS",
    "config_changelog_visibility_barrier",
    "ensure_repeatable_read_snapshot",
    "get_latest_config_changelog_cursor_in_session",
    "record_config_changelog_entry",
]
