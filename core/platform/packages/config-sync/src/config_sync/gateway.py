"""Dedicated Shopify-style Control Plane Config Watch Gateway ASGI factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from config_sync.adapters.inbound.fastapi_watch_router import create_config_sync_router
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from config_sync.ports.config_watch_auth_port import ConfigWatchAuthStrategyPort
from config_sync.provider import ConfigSyncProvider

logger = structlog.get_logger(__name__)


def create_config_watch_gateway_app(
    *,
    database_url: str,
    changelog_repo: ConfigChangelogRepositoryPort,
    providers: Iterable[ConfigCatalogProviderPort],
    internal_token: str | None = None,
    auth_strategy: ConfigWatchAuthStrategyPort | None = None,
    broadcaster: ConfigBroadcasterPort | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    """Creates a dedicated Watch Gateway ASGI app isolated from the web API container.

    Runs `PostgresNotifyConfigBroadcasterBridge` (`LISTEN config_sync_changelog`) in its
    lifespan so thousands of Data Plane shards receive `<5ms` zero-poll SSE delta pushes
    across horizontally scaled gateway replicas, while keeping `unified-api` 100% pure HTTP.
    """
    resolved_broadcaster = broadcaster or ConfigSyncProvider.create_broadcaster()
    stream_use_case = ConfigSyncProvider.create_stream_use_case(
        providers=providers,
        broadcaster=resolved_broadcaster,
    )
    notify_bridge = ConfigSyncProvider.create_notify_bridge(
        database_url=database_url,
        changelog_repo=changelog_repo,
        broadcaster=resolved_broadcaster,
    )

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("config_watch_gateway_starting")
        notify_bridge.start()
        try:
            yield
        finally:
            await notify_bridge.stop()
            if on_shutdown is not None:
                await on_shutdown()
            logger.info("config_watch_gateway_stopped")

    app = FastAPI(
        title="Soopa Control Plane Config Watch Gateway",
        lifespan=_lifespan,
    )
    app.include_router(
        create_config_sync_router(
            use_case_provider=lambda: stream_use_case,
            internal_bearer_token=internal_token,
            auth_strategy=auth_strategy,
        )
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "config-watch-gateway"}

    return app


__all__ = ["create_config_watch_gateway_app"]
