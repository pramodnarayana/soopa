"""Linearizable `xid8` Drain-Until-Empty Changelog Cursor Tailer feeding ConfigBroadcasterPort."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable

import structlog

from config_sync.domain.dtos import ChangelogVisibilityWatermark, ConfigCursor
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort

logger = structlog.get_logger(__name__)


class ChangelogCursorBroadcasterBridge:
    """Tails `config_sync.config_changelog` using a linearizable `(txid, version)` Drain-Until-Empty loop.

    Replaces PostgreSQL `LISTEN/NOTIFY` with a PgBouncer/RDS-Proxy/read-replica-safe
    composite `(txid, version)` cursor strictly behind `pg_snapshot_xmin(pg_current_snapshot())`
    so control-plane writes incur zero `AsyncQueueLock` serialization and concurrent commits
    are always broadcast in strictly increasing total order with zero skipped rows.
    """

    def __init__(
        self,
        *,
        changelog_repo: ConfigChangelogRepositoryPort,
        broadcaster: ConfigBroadcasterPort,
        poll_interval_seconds: float = 0.15,
        batch_size: int = 500,
        error_backoff_seconds: float = 1.0,
        visibility_lag_check_interval_seconds: float = 5.0,
        visibility_lag_alert_seconds: float = 5.0,
        initial_cursor: ConfigCursor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if error_backoff_seconds <= 0:
            raise ValueError("error_backoff_seconds must be positive")
        if visibility_lag_check_interval_seconds <= 0:
            raise ValueError("visibility_lag_check_interval_seconds must be positive")
        if visibility_lag_alert_seconds < 0:
            raise ValueError("visibility_lag_alert_seconds cannot be negative")
        if initial_cursor is not None and (initial_cursor.txid < 0 or initial_cursor.version < 0):
            raise ValueError("initial_cursor components cannot be negative")

        self._changelog_repo = changelog_repo
        self._broadcaster = broadcaster
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._error_backoff_seconds = error_backoff_seconds
        self._visibility_lag_check_interval_seconds = visibility_lag_check_interval_seconds
        self._visibility_lag_alert_seconds = visibility_lag_alert_seconds
        self._clock = clock

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._cursor_initialized: bool = initial_cursor is not None
        self._last_dispatched_cursor: ConfigCursor = (
            initial_cursor if initial_cursor is not None else ConfigCursor.zero()
        )
        self._last_lag_check_at: float | None = None
        self._lag_started_at: float | None = None

    @property
    def last_dispatched_cursor(self) -> ConfigCursor:
        return self._last_dispatched_cursor

    @property
    def last_dispatched_version(self) -> int:
        return self._last_dispatched_cursor.version

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "config_sync_cursor_bridge_started",
            poll_interval_seconds=self._poll_interval_seconds,
            batch_size=self._batch_size,
            initial_cursor=self._last_dispatched_cursor.encode()
            if self._cursor_initialized
            else None,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info(
            "config_sync_cursor_bridge_stopped",
            last_dispatched_cursor=self._last_dispatched_cursor.encode(),
        )

    async def initialize_cursor(self) -> ConfigCursor:
        """Aligns the tailer cursor to the current global visibility-safe `(txid, version)` head."""
        if not self._cursor_initialized:
            self._last_dispatched_cursor = await self._changelog_repo.get_global_safe_cursor()
            self._cursor_initialized = True
            logger.info(
                "config_sync_cursor_bridge_initialized",
                cursor=self._last_dispatched_cursor.encode(),
            )
        return self._last_dispatched_cursor

    async def poll_once(self) -> int:
        """Reads and broadcasts a single bounded batch of visibility-safe changelog entries."""
        entries = await self._changelog_repo.get_entries_after_cursor(
            since_cursor=self._last_dispatched_cursor,
            limit=self._batch_size,
        )
        for entry in entries:
            await self._broadcaster.publish_delta(entry)
            if entry.cursor > self._last_dispatched_cursor:
                self._last_dispatched_cursor = entry.cursor
        return len(entries)

    async def drain_until_empty(self) -> int:
        """Drains all currently visible changelog deltas with zero sleep between full batches."""
        total_published = 0
        while True:
            batch_count = await self.poll_once()
            total_published += batch_count
            if batch_count < self._batch_size:
                break
        return total_published

    async def check_visibility_lag(self) -> ChangelogVisibilityWatermark:
        """Monitors whether an unrelated long-running write transaction stalls `pg_snapshot_xmin`."""
        watermark = await self._changelog_repo.get_visibility_lag_metrics()
        now = self._clock()
        self._last_lag_check_at = now
        if watermark.is_lagged:
            if self._lag_started_at is None:
                self._lag_started_at = now
            stalled_seconds = now - self._lag_started_at
            if stalled_seconds >= self._visibility_lag_alert_seconds:
                logger.error(
                    "config_sync_visibility_horizon_stalled",
                    safe_cursor=watermark.safe_cursor.encode(),
                    raw_max_cursor=watermark.raw_max_cursor.encode(),
                    lagged_txids=watermark.lagged_txids,
                    stalled_seconds=round(stalled_seconds, 3),
                )
        else:
            self._lag_started_at = None
        return watermark

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if not self._cursor_initialized:
                    await self.initialize_cursor()
                published = await self.drain_until_empty()
                if published == 0:
                    now = self._clock()
                    if (
                        self._last_lag_check_at is None
                        or now - self._last_lag_check_at
                        >= self._visibility_lag_check_interval_seconds
                    ):
                        await self.check_visibility_lag()
                    await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "config_sync_cursor_bridge_error",
                    last_dispatched_cursor=self._last_dispatched_cursor.encode(),
                    error=str(exc),
                )
                if self._running:
                    await asyncio.sleep(self._error_backoff_seconds)


__all__ = ["ChangelogCursorBroadcasterBridge"]
