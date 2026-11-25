"""EDI Config Sync Worker — Queue-Free HTTPS Dynamic Watch Data Plane Synchronizer."""

from __future__ import annotations

import asyncio

import structlog
from config_sync.application.multi_tenant_watch_manager import MultiTenantConfigWatchManager
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from config_sync.provider import ConfigSyncProvider
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.config_sync import EdiShardConfigSink
from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.domain.enums import EDI_CONFIG_APP_ID
from observability import ObservabilityProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

from config_sync_worker.provision.settings import get_settings

load_dotenv()
logger = structlog.get_logger(__name__)


class EdiConfigSyncWorkerModule(LaunchableWorker):
    """Maintains outbound HTTPS/SSE Dynamic Watch streams syncing EDI Control Plane config to tenant shards."""

    def __init__(self) -> None:
        self.db_router: DatabaseRouter | None = None
        self._tenant_resolver: SqlAlchemyTenantResolver | None = None
        self._watch_manager: MultiTenantConfigWatchManager | None = None

    async def start(self) -> None:
        logger.info("config_sync_worker_starting_dynamic_watch")
        settings = get_settings()
        db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        tenant_resolver = SqlAlchemyTenantResolver(db_router)
        self.db_router = db_router
        self._tenant_resolver = tenant_resolver

        watch_base_url = settings.config_watch_base_url.strip()
        if not watch_base_url.startswith(("http://", "https://")):
            raise ValueError(
                f"CONFIG_WATCH_BASE_URL must start with 'http://' or 'https://', got {watch_base_url!r}."
            )
        watch_token = settings.config_watch_token.strip() or None
        watch_client = ConfigSyncProvider.create_sse_watch_client(
            base_url=watch_base_url,
            bearer_token=watch_token,
        )

        def _create_sink(tenant_id: str) -> ConfigApplySinkPort:
            return EdiShardConfigSink(
                db_router=db_router,
                tenant_port=tenant_resolver,
                tenant_id=tenant_id,
            )

        self._watch_manager = ConfigSyncProvider.create_multi_tenant_watch_manager(
            app_id=EDI_CONFIG_APP_ID,
            watch_client=watch_client,
            tenant_ids_provider=tenant_resolver.get_all_tenant_ids,
            sink_factory=_create_sink,
            discovery_interval_seconds=settings.config_watch_tenant_discovery_seconds,
        )
        self._watch_manager.start()
        logger.info(
            "config_sync_worker_dynamic_watch_started",
            watch_base_url=watch_base_url,
        )

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self._watch_manager is None:
            return []
        return self._watch_manager.background_tasks()

    async def stop(self) -> None:
        logger.info("config_sync_worker_shutting_down")
        if self._watch_manager is not None:
            await self._watch_manager.stop()
            self._watch_manager = None
        if self.db_router is not None:
            await self.db_router.close_all()
        logger.info("config_sync_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("config-sync-worker")
    module = EdiConfigSyncWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
