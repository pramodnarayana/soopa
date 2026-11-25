"""PostgreSQL LISTEN/NOTIFY bridge feeding committed config changelog deltas into ConfigBroadcasterPort."""

from __future__ import annotations

import asyncio
import contextlib
import json

import asyncpg
import structlog
from database.utils import normalize_to_standard_postgres

from config_sync.domain.enums import ConfigSyncChannel
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort

logger = structlog.get_logger(__name__)


class PostgresNotifyConfigBroadcasterBridge:
    """Maintains an asyncpg LISTEN connection to fan out config deltas across multi-replica pods.

    Tracks `_last_dispatched_version` and runs a bounded catch-up sweep via
    `get_entries_after_version()` on every reconnect or burst queue overflow so zero
    committed changelog deltas are ever skipped during PostgreSQL failovers or bursts.
    """

    _CATCHUP_BATCH_SIZE: int = 500

    def __init__(
        self,
        *,
        database_url: str,
        changelog_repo: ConfigChangelogRepositoryPort,
        broadcaster: ConfigBroadcasterPort,
        channel: str = ConfigSyncChannel.CONFIG_CHANGELOG_NOTIFY.value,
        reconnect_sleep_seconds: float = 1.0,
    ) -> None:
        self._dsn = normalize_to_standard_postgres(database_url)
        self._changelog_repo = changelog_repo
        self._broadcaster = broadcaster
        self._channel = channel
        self._reconnect_sleep_seconds = reconnect_sleep_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._pending_versions: asyncio.Queue[int] = asyncio.Queue(maxsize=4096)
        self._last_dispatched_version: int = 0
        self._catchup_needed: bool = False

    @property
    def last_dispatched_version(self) -> int:
        return self._last_dispatched_version

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("config_sync_notify_bridge_started", channel=self._channel)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("config_sync_notify_bridge_stopped", channel=self._channel)

    def _on_notify(
        self,
        _connection: asyncpg.Connection[asyncpg.Record],
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        try:
            parsed = json.loads(payload)
            version = parsed.get("version") if isinstance(parsed, dict) else None
            if isinstance(version, int) and version > 0:
                self._pending_versions.put_nowait(version)
        except asyncio.QueueFull:
            self._catchup_needed = True
            logger.error(
                "config_sync_notify_queue_overflow_triggering_catchup",
                channel=self._channel,
                last_dispatched_version=self._last_dispatched_version,
            )
        except json.JSONDecodeError as exc:
            logger.error(
                "config_sync_notify_invalid_json_payload",
                channel=self._channel,
                error=str(exc),
            )

    async def _dispatch_version(self, version: int) -> None:
        if version <= self._last_dispatched_version:
            return
        delta = await self._changelog_repo.get_entry_by_version(version=version)
        if delta is None:
            logger.error("config_sync_notify_version_not_found", version=version)
            return
        await self._broadcaster.publish_delta(delta)
        self._last_dispatched_version = max(self._last_dispatched_version, delta.version)

    async def catch_up_missed_entries(self) -> int:
        """Drains any committed changelog entries newer than `_last_dispatched_version` in chunks."""
        self._catchup_needed = False
        total_replayed = 0
        while self._running or total_replayed == 0:
            entries = await self._changelog_repo.get_entries_after_version(
                since_version=self._last_dispatched_version,
                limit=self._CATCHUP_BATCH_SIZE,
            )
            if not entries:
                break
            for entry in entries:
                await self._broadcaster.publish_delta(entry)
                self._last_dispatched_version = max(self._last_dispatched_version, entry.version)
                total_replayed += 1
            if len(entries) < self._CATCHUP_BATCH_SIZE:
                break
        if total_replayed > 0:
            logger.info(
                "config_sync_notify_bridge_caught_up",
                replayed_count=total_replayed,
                last_dispatched_version=self._last_dispatched_version,
            )
        return total_replayed

    async def _run_loop(self) -> None:
        has_connected_once = False
        while self._running:
            conn: asyncpg.Connection[asyncpg.Record] | None = None
            try:
                conn = await asyncpg.connect(self._dsn)
                await conn.add_listener(self._channel, self._on_notify)
                logger.info("config_sync_notify_bridge_listening", channel=self._channel)
                if has_connected_once and self._last_dispatched_version > 0:
                    await self.catch_up_missed_entries()
                has_connected_once = True

                while self._running:
                    if self._catchup_needed:
                        await self.catch_up_missed_entries()
                    try:
                        version = await asyncio.wait_for(self._pending_versions.get(), timeout=5.0)
                    except TimeoutError:
                        await conn.execute("SELECT 1")
                        continue
                    await self._dispatch_version(version)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "config_sync_notify_bridge_error",
                    channel=self._channel,
                    error=str(exc),
                )
                if self._running:
                    await asyncio.sleep(self._reconnect_sleep_seconds)
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.remove_listener(self._channel, self._on_notify)
                    with contextlib.suppress(Exception):
                        await conn.close()


__all__ = ["PostgresNotifyConfigBroadcasterBridge"]
