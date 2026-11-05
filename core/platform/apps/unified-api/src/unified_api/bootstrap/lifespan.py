"""
Shell Application Lifespan.

The Shell (Host) owns the process lifecycle and orchestrates startup and
shutdown of all domain workers in the correct order.

Architecture note:
  - Starlette does NOT call mounted sub-app lifespans when the parent app
    has its own lifespan. All domain initialization is therefore delegated
    through explicit startup/shutdown hooks called here.
  - This module is the ONLY place allowed to import startup/shutdown hooks
    from multiple domains simultaneously.
  - Startup order: UCP workers → Notification Engine → EDI infrastructure.
  - Shutdown order (reverse): EDI infrastructure → Notification Engine → UCP workers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from database.provider import DatabaseProvider
from database.router import DatabaseRouter
from dependency_injector import providers
from edi.bootstrap.lifespan import shutdown, startup
from fastapi import FastAPI
from notification.bootstrap.lifespan import shutdown as notification_shutdown
from notification.bootstrap.lifespan import startup as notification_startup
from starlette.routing import Mount
from ucp.bootstrap.lifespan import shutdown as ucp_shutdown
from ucp.bootstrap.lifespan import startup as ucp_startup

from unified_api.bootstrap.identity_drift_guard import verify_platform_tenant_idp_alignment
from unified_api.settings import get_settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def shell_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Shell application lifespan context manager."""
    settings = getattr(app.state, "settings", None) or get_settings()
    db_url = os.environ.get("DATABASE_URL") or str(settings.database.global_url)
    db_provider = DatabaseProvider.from_url(db_url)
    app.state.db_provider = db_provider
    try:
        await verify_platform_tenant_idp_alignment(
            db_provider=db_provider,
            expected_platform_org_id=settings.identity.platform_org_id,
        )

        ucp_container = getattr(app.state, "ucp_container", None)
        if ucp_container is not None:
            ucp_container.db_provider.override(providers.Object(db_provider))

        logger.info("shell_startup_ucp_initializing")
        await ucp_startup()
        try:
            logger.info("shell_startup_notification_initializing")
            await notification_startup()
            try:
                db_router = DatabaseRouter(
                    global_db_url=db_url,
                    pool_size=settings.database.pool_size,
                    max_overflow=settings.database.max_overflow,
                    shard_overrides=settings.database.shard_overrides or {},
                )
                app.state.db_router = db_router

                edi_app = next(
                    (
                        route.app
                        for route in app.routes
                        if isinstance(route, Mount) and route.path == ""
                    ),
                    None,
                )
                if edi_app is not None and isinstance(edi_app, FastAPI):
                    edi_app.state.db_provider = db_provider
                    logger.info("shell_startup_edi_initializing")
                    await startup(edi_app, db_router=db_router)
                    app.state.edi_app = edi_app
                    if hasattr(edi_app.state, "tenant_resolver"):
                        app.state.tenant_resolver = edi_app.state.tenant_resolver

                try:
                    yield
                finally:
                    if edi_app is not None and isinstance(edi_app, FastAPI):
                        logger.info("shell_shutdown_edi_stopping")
                        await shutdown(edi_app)
                        app.state.edi_app = None
                        app.state.tenant_resolver = None
                    logger.info("shell_shutdown_closing_db_router")
                    await db_router.close_all()
            finally:
                logger.info("shell_shutdown_notification_stopping")
                await notification_shutdown()
        finally:
            logger.info("shell_shutdown_ucp_stopping")
            await ucp_shutdown()
    finally:
        logger.info("shell_shutdown_closing_db_provider")
        await db_provider.close()
