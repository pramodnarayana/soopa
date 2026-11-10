"""Shell Application Lifespan.

The Shell (Host) owns the shared DatabaseProvider and DatabaseRouter and orchestrates
startup and shutdown of Core Platform hooks and all dynamically loaded LaunchableApiModule
plugins in deterministic order.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import structlog
from database.provider import DatabaseProvider
from database.router import DatabaseRouter
from dependency_injector import providers
from fastapi import FastAPI
from notification.bootstrap.lifespan import shutdown as notification_shutdown
from notification.bootstrap.lifespan import startup as notification_startup
from seedwork.infra.api import LaunchableApiModule
from ucp.bootstrap.lifespan import shutdown as ucp_shutdown
from ucp.bootstrap.lifespan import startup as ucp_startup

from unified_api.bootstrap.identity_drift_guard import verify_platform_tenant_idp_alignment
from unified_api.settings import get_settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def _module_lifecycle(
    app: FastAPI,
    db_router: DatabaseRouter,
    api_modules: list[LaunchableApiModule],
) -> AsyncGenerator[None, None]:
    started_modules: list[LaunchableApiModule] = []
    try:
        for module in api_modules:
            logger.info("shell_startup_module_initializing", module=module.name)
            await module.startup(app, db_router)
            started_modules.append(module)

        try:
            edi_app = app.state.edi_app
        except AttributeError:
            edi_app = None
        if edi_app is not None:
            with suppress(AttributeError):
                app.state.tenant_resolver = edi_app.state.tenant_resolver

        yield
    finally:
        for module in reversed(started_modules):
            logger.info("shell_shutdown_module_stopping", module=module.name)
            try:
                await module.shutdown(app)
            except Exception:
                logger.exception("shell_shutdown_module_failed", module=module.name)
        app.state.tenant_resolver = None
        logger.info("shell_shutdown_closing_db_router")
        await db_router.close_all()


@asynccontextmanager
async def shell_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Shell application lifespan context manager."""
    try:
        settings = app.state.settings
    except AttributeError:
        settings = get_settings()
    db_url = os.environ.get("DATABASE_URL") or str(settings.database.global_url)
    db_provider = DatabaseProvider.from_url(db_url)
    app.state.db_provider = db_provider
    try:
        await verify_platform_tenant_idp_alignment(
            db_provider=db_provider,
            expected_platform_org_id=settings.identity.platform_org_id,
        )

        try:
            ucp_container = app.state.ucp_container
        except AttributeError:
            ucp_container = None
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
                api_modules: list[LaunchableApiModule] = list(app.state.api_modules)
                async with _module_lifecycle(app, db_router, api_modules):
                    yield
            finally:
                logger.info("shell_shutdown_notification_stopping")
                await notification_shutdown()
        finally:
            logger.info("shell_shutdown_ucp_stopping")
            await ucp_shutdown()
    finally:
        logger.info("shell_shutdown_closing_db_provider")
        await db_provider.close()
