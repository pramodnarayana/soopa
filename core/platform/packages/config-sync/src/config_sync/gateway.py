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
    changelog_repo: ConfigChangelogRepositoryPort,
    providers: Iterable[ConfigCatalogProviderPort],
    internal_token: str | None = None,
    auth_strategy: ConfigWatchAuthStrategyPort | None = None,
    broadcaster: ConfigBroadcasterPort | None = None,
    poll_interval_seconds: float = 0.15,
    batch_size: int = 500,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    """Creates a dedicated Watch Gateway ASGI app isolated from the web API container.

    Runs `ChangelogCursorBroadcasterBridge` (linearizable `xid8` Drain-Until-Empty tailer)
    in its lifespan so thousands of Data Plane shards receive sub-150ms SSE delta pushes
    across horizontally scaled gateway replicas with zero `AsyncQueueLock` contention,
    full PgBouncer/RDS-Proxy compatibility, and a 100% pure stateless `unified-api`.
    """
    resolved_broadcaster = broadcaster or ConfigSyncProvider.create_broadcaster()
    stream_use_case = ConfigSyncProvider.create_stream_use_case(
        providers=providers,
        broadcaster=resolved_broadcaster,
    )
    cursor_bridge = ConfigSyncProvider.create_cursor_broadcaster_bridge(
        changelog_repo=changelog_repo,
        broadcaster=resolved_broadcaster,
        poll_interval_seconds=poll_interval_seconds,
        batch_size=batch_size,
    )

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("config_watch_gateway_starting")
        cursor_bridge.start()
        try:
            yield
        finally:
            await cursor_bridge.stop()
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
