"""LaunchableApiModule implementation for the Integration Platform (IP) bounded context."""

from __future__ import annotations

import structlog
from database.router import DatabaseRouterPort
from fastapi import FastAPI
from ip.engine.adapters.inbound.api.routers.catalog_router import router as catalog_router
from ip.engine.adapters.inbound.api.routers.connections_router import router as connections_router
from ip.engine.adapters.inbound.api.routers.ingress_router import router as ingress_router
from ip.engine.adapters.inbound.api.routers.stitches_router import router as stitches_router
from ip.engine.adapters.inbound.api.routers.sync_runs_router import router as sync_runs_router
from ip.engine.adapters.inbound.api.routers.transactions_router import (
    router as transactions_router,
)
from ip.engine.adapters.inbound.api.routers.transformations_router import (
    router as transformations_router,
)
from ip.engine.lifespan import shutdown as ip_shutdown
from ip.engine.lifespan import startup as ip_startup
from ip.engine.settings import get_ip_engine_settings

logger = structlog.get_logger(__name__)


class IpApiModule:
    """Self-contained API module for the Integration Platform (IP) bounded context."""

    @property
    def name(self) -> str:
        return "ip"

    def register_routes(self, app: FastAPI) -> None:
        """Registers all Integration Platform HTTP routers on the host FastAPI shell."""
        app.include_router(connections_router)
        app.include_router(catalog_router)
        app.include_router(ingress_router)
        app.include_router(transformations_router)
        app.include_router(sync_runs_router)
        app.include_router(stitches_router)
        app.include_router(transactions_router)
        logger.info("ip_api_module_routes_registered")

    async def startup(self, app: FastAPI, db_router: DatabaseRouterPort) -> None:
        """Initializes the IP IoC Container and tenant resolver using the shared DatabaseRouter."""
        settings = get_ip_engine_settings()
        await ip_startup(
            app,
            db_router=db_router,
            allow_private_ips=settings.allow_private_ips,
        )

    async def shutdown(self, app: FastAPI) -> None:
        """Gracefully cleans up IP container and resolver state on application shutdown."""
        await ip_shutdown(app)


__all__ = ["IpApiModule"]
