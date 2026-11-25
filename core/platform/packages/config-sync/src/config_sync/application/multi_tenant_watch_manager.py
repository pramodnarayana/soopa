"""Multi-tenant orchestrator launching one autonomous Dynamic Watch loop per active tenant."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import structlog

from config_sync.application.sync_config_watch_loop_use_case import (
    SyncConfigWatchLoopUseCase,
    WatchLoopConfig,
)
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from config_sync.ports.config_watch_client_port import ConfigWatchClientPort

logger = structlog.get_logger(__name__)

TenantIdsProvider = Callable[[], Awaitable[Sequence[str]]]
TenantSinkFactory = Callable[[str], ConfigApplySinkPort]


class MultiTenantConfigWatchManager:
    """Discovers active tenants and maintains one autonomous `SyncConfigWatchLoopUseCase` per tenant.

    Reused across EDI, IP, and future apps so tenant discovery, loop deduplication,
    tenant de-provisioning cleanup, and graceful shutdown are never duplicated.
    """

    def __init__(
        self,
        *,
        app_id: str,
        watch_client: ConfigWatchClientPort,
        tenant_ids_provider: TenantIdsProvider,
        sink_factory: TenantSinkFactory,
        discovery_interval_seconds: float = 30.0,
        initial_backoff_seconds: float = 0.1,
        max_backoff_seconds: float = 5.0,
    ) -> None:
        self._app_id = app_id
        self._watch_client = watch_client
        self._tenant_ids_provider = tenant_ids_provider
        self._sink_factory = sink_factory
        self._discovery_interval_seconds = max(1.0, discovery_interval_seconds)
        self._initial_backoff_seconds = initial_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds

        self._running = False
        self._stop_event = asyncio.Event()
        self._discovery_task: asyncio.Task[None] | None = None
        self._tenant_loops: dict[str, SyncConfigWatchLoopUseCase] = {}

    @property
    def watched_tenant_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tenant_loops.keys()))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._discovery_task = asyncio.create_task(
            self._discovery_loop(),
            name=f"config_watch_discovery:{self._app_id}",
        )
        logger.info(
            "multi_tenant_config_watch_manager_started",
            app_id=self._app_id,
            discovery_interval_seconds=self._discovery_interval_seconds,
        )

    async def reconcile_tenants_once(self) -> int:
        """Discovers active tenants, attaches new watch loops, and stops removed tenants."""
        tenant_ids = await self._tenant_ids_provider()
        active_set = {tid for tid in tenant_ids if tid}
        started = 0
        for tenant_id in sorted(active_set):
            if tenant_id in self._tenant_loops:
                continue
            sink = self._sink_factory(tenant_id)
            loop = SyncConfigWatchLoopUseCase(
                watch_client=self._watch_client,
                sink=sink,
                config=WatchLoopConfig(
                    app_id=self._app_id,
                    tenant_id=tenant_id,
                    initial_backoff_seconds=self._initial_backoff_seconds,
                    max_backoff_seconds=self._max_backoff_seconds,
                ),
            )
            loop.start()
            self._tenant_loops[tenant_id] = loop
            started += 1

        removed = [tid for tid in self._tenant_loops if tid not in active_set]
        for tid in removed:
            loop = self._tenant_loops.pop(tid)
            await loop.stop()
            logger.info(
                "multi_tenant_config_watch_tenant_detached",
                app_id=self._app_id,
                tenant_id=tid,
            )

        if started > 0:
            logger.info(
                "multi_tenant_config_watch_tenants_attached",
                app_id=self._app_id,
                newly_attached=started,
                total_watched=len(self._tenant_loops),
            )
        return started

    async def _discovery_loop(self) -> None:
        while self._running:
            try:
                await self.reconcile_tenants_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "multi_tenant_config_watch_discovery_failed",
                    app_id=self._app_id,
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._discovery_interval_seconds,
                )
            except TimeoutError:
                continue

    def background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self._discovery_task is not None:
            tasks.append(self._discovery_task)
        for loop in self._tenant_loops.values():
            tasks.extend(loop.background_tasks())
        return tasks

    async def stop(self) -> None:
        if not self._running and not self._tenant_loops and self._discovery_task is None:
            return
        self._running = False
        self._stop_event.set()
        if self._discovery_task is not None and not self._discovery_task.done():
            self._discovery_task.cancel()
            await asyncio.gather(self._discovery_task, return_exceptions=True)
        self._discovery_task = None

        for loop in list(self._tenant_loops.values()):
            await loop.stop()
        self._tenant_loops.clear()
        logger.info("multi_tenant_config_watch_manager_stopped", app_id=self._app_id)


__all__ = ["MultiTenantConfigWatchManager", "TenantIdsProvider", "TenantSinkFactory"]
