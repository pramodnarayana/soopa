"""LaunchableApiModule Composition Root for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from collections.abc import Callable

import structlog
from database.router import DatabaseRouterPort
from fastapi import FastAPI

from ip.engine.adapters.inbound.api.routers.catalog_router import router as catalog_router
from ip.engine.adapters.inbound.api.routers.connections_router import router as connections_router
from ip.engine.adapters.inbound.api.routers.ingress_router import router as ingress_router
from ip.engine.adapters.inbound.api.routers.records_router import router as records_router
from ip.engine.adapters.inbound.api.routers.replay_router import router as replay_router
from ip.engine.adapters.inbound.api.routers.stitches_router import router as stitches_router
from ip.engine.adapters.inbound.api.routers.sync_runs_router import router as sync_runs_router
from ip.engine.adapters.inbound.api.routers.trace_router import router as trace_router
from ip.engine.adapters.inbound.api.routers.transformations_router import (
    router as transformations_router,
)
from ip.engine.application.api_provider_port import IpApiProviderPort
from ip.engine.bootstrap.api_provider import IpApiProvider
from ip.engine.bootstrap.container import Container
from ip.engine.bootstrap.lifespan import shutdown as ip_shutdown
from ip.engine.bootstrap.lifespan import startup as ip_startup
from ip.engine.settings import get_ip_engine_settings

logger = structlog.get_logger(__name__)


class IpApiModule:
    """Self-contained API module for the Integration Platform (IP) Engine."""

    def __init__(
        self,
        *,
        api_provider_factory: Callable[[], IpApiProviderPort] | None = None,
        container_configurator: Callable[[Container], object] | None = None,
    ) -> None:
        self._api_provider_factory = api_provider_factory or IpApiProvider
        self._container_configurator = container_configurator

    @property
    def name(self) -> str:
        return "ip"

    def register_routes(self, app: FastAPI) -> None:
        """Registers all Integration Platform HTTP routers and attaches IpApiProvider onto `app.state`."""
        app.state.ip_api_provider = self._api_provider_factory()
        app.include_router(connections_router)
        app.include_router(catalog_router)
        app.include_router(ingress_router)
        app.include_router(transformations_router)
        app.include_router(sync_runs_router)
        app.include_router(stitches_router)
        app.include_router(trace_router)
        app.include_router(replay_router)
        app.include_router(records_router)
        logger.info("ip_api_module_routes_registered")

    async def startup(self, app: FastAPI, db_router: DatabaseRouterPort) -> None:
        """Initializes the IP IoC Container and tenant resolver using the shared DatabaseRouter."""
        try:
            existing_provider = app.state.ip_api_provider
        except AttributeError:
            existing_provider = None
        if existing_provider is None:
            app.state.ip_api_provider = self._api_provider_factory()

        settings = get_ip_engine_settings()
        await ip_startup(
            app,
            db_router=db_router,
            allow_private_ips=settings.allow_private_ips,
            container_configurator=self._container_configurator,
        )

    async def shutdown(self, app: FastAPI) -> None:
        """Gracefully cleans up IP container and resolver state on application shutdown."""
        await ip_shutdown(app)


__all__ = ["IpApiModule"]
