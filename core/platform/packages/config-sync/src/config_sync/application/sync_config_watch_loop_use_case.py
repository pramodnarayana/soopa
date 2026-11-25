"""Data Plane autonomous Dynamic Watch synchronization loop with exponential reconnect backoff."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from dataclasses import dataclass

import structlog

from config_sync.domain.checksum import verify_delta_checksum, verify_snapshot_checksum
from config_sync.domain.dtos import (
    ConfigDeltaEvent,
    ConfigSnapshot,
    ConfigSyncError,
    ConfigWatchHeartbeat,
)
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from config_sync.ports.config_watch_client_port import ConfigWatchClientPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class WatchLoopConfig:
    """Co-located immutable configuration for a Data Plane Dynamic Watch loop."""

    app_id: str
    tenant_id: str
    initial_backoff_seconds: float = 0.1
    max_backoff_seconds: float = 5.0


class SyncConfigWatchLoopUseCase:
    """Maintains a persistent outbound Dynamic Watch connection, enforcing checksums and monotonicity."""

    def __init__(
        self,
        *,
        watch_client: ConfigWatchClientPort,
        sink: ConfigApplySinkPort,
        config: WatchLoopConfig,
    ) -> None:
        self._watch_client = watch_client
        self._sink = sink
        self._config = config
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_applied_version: int = 0

    @property
    def last_applied_version(self) -> int:
        return self._last_applied_version

    @property
    def is_running(self) -> bool:
        return self._running

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return [self._task] if self._task is not None else []

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self.run_forever())
        logger.info(
            "config_watch_loop_started",
            app_id=self._config.app_id,
            tenant_id=self._config.tenant_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info(
            "config_watch_loop_stopped",
            app_id=self._config.app_id,
            tenant_id=self._config.tenant_id,
            last_applied_version=self._last_applied_version,
        )

    async def sync_once(self) -> int:
        """Consumes one watch session until the stream closes, returning the latest applied version."""
        current_version = await self._sink.get_current_version(
            app_id=self._config.app_id,
            tenant_id=self._config.tenant_id,
        )
        self._last_applied_version = max(self._last_applied_version, current_version)
        bound = logger.bind(
            app_id=self._config.app_id,
            tenant_id=self._config.tenant_id,
        )

        async for item in self._watch_client.watch(
            app_id=self._config.app_id,
            tenant_id=self._config.tenant_id,
            since_version=self._last_applied_version,
        ):
            if isinstance(item, ConfigSyncError):
                bound.error(
                    "config_watch_stream_error_received",
                    code=item.code.value,
                    message=item.message,
                )
                break

            if isinstance(item, ConfigWatchHeartbeat):
                bound.debug("config_watch_heartbeat_received", latest_version=item.latest_version)
                continue

            if isinstance(item, ConfigSnapshot):
                if not verify_snapshot_checksum(item):
                    bound.error(
                        "config_watch_snapshot_checksum_mismatch",
                        version=item.version,
                        declared_checksum=item.checksum,
                    )
                    continue
                if item.version < self._last_applied_version:
                    bound.info(
                        "config_watch_stale_snapshot_dropped",
                        incoming_version=item.version,
                        local_version=self._last_applied_version,
                    )
                    continue
                await self._sink.apply_snapshot(item)
                self._last_applied_version = item.version
                bound.info(
                    "config_watch_snapshot_applied",
                    version=item.version,
                    entity_count=len(item.entities),
                )
                continue

            if isinstance(item, ConfigDeltaEvent):
                if not verify_delta_checksum(item):
                    bound.error(
                        "config_watch_delta_checksum_mismatch",
                        event_id=item.event_id,
                        version=item.version,
                    )
                    continue
                if item.version <= self._last_applied_version:
                    bound.info(
                        "config_watch_stale_delta_dropped",
                        event_id=item.event_id,
                        incoming_version=item.version,
                        local_version=self._last_applied_version,
                    )
                    continue
                await self._sink.apply_delta(item)
                self._last_applied_version = item.version
                bound.info(
                    "config_watch_delta_applied",
                    event_id=item.event_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    action=item.action.value,
                    version=item.version,
                )

        return self._last_applied_version

    async def run_forever(self) -> None:
        backoff = self._config.initial_backoff_seconds
        while self._running:
            try:
                before = self._last_applied_version
                await self.sync_once()
                if self._last_applied_version > before:
                    backoff = self._config.initial_backoff_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "config_watch_connection_failed",
                    app_id=self._config.app_id,
                    tenant_id=self._config.tenant_id,
                    backoff_seconds=backoff,
                    error=str(exc),
                )

            if not self._running:
                break
            jitter = (secrets.randbelow(200) / 1000.0) * backoff
            await asyncio.sleep(min(self._config.max_backoff_seconds, backoff + jitter))
            backoff = min(self._config.max_backoff_seconds, backoff * 2.0)


__all__ = ["SyncConfigWatchLoopUseCase", "WatchLoopConfig"]
