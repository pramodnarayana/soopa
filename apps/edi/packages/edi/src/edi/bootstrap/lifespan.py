"""
EDI Domain Startup and Shutdown Hooks.

These hooks initialize and tear down EDI infrastructure resources on the EDI
sub-application's typed state without mutable module-level singletons or
attribute reflection.
"""

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from dependency_injector import providers
from fastapi import FastAPI

from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.bootstrap.container import Container

logger = structlog.get_logger(__name__)


async def startup(
    app: FastAPI,
    *,
    global_db_url: str = "",
    pool_size: int = 10,
    max_overflow: int = 20,
    shard_overrides: dict[str, str] | None = None,
    db_router: DatabaseRouterPort | None = None,
) -> None:
    """
    Initializes the EDI DatabaseRouter and attaches it to ``app.state``.
    """
    owns_db_router = db_router is None
    if db_router is not None:
        logger.info("edi_attaching_shared_db_router")
        resolved_router: DatabaseRouterPort = db_router
    else:
        logger.info("edi_initializing_db_router")
        resolved_router = DatabaseRouter(
            global_db_url=global_db_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            shard_overrides=shard_overrides or {},
        )

    app.state.db_router = resolved_router
    app.state.owns_db_router = owns_db_router

    resolver = SqlAlchemyTenantResolver(resolved_router)
    app.state.tenant_resolver = resolver

    container: Container | None = app.state.edi_container
    if container is not None:
        container.tenant_resolver.override(providers.Object(resolver))

    logger.info("edi_db_router_initialized")


async def shutdown(app: FastAPI | None = None) -> None:
    """
    Gracefully closes the EDI DatabaseRouter connection pool and container resources.
    """
    if app is None:
        return

    container: Container | None = app.state.edi_container
    if container is not None:
        logger.info("edi_shutting_down_as2_tester")
        try:
            tester = container.as2_tester()
            if isinstance(tester, HttpxAS2TesterAdapter):
                await tester.close()
        except Exception:
            logger.exception("edi_as2_tester_close_failed")

    db_router: DatabaseRouterPort | None = app.state.db_router
    owns_db_router: bool = bool(app.state.owns_db_router)
    if db_router is not None and owns_db_router:
        logger.info("edi_shutting_down_db_router")
        try:
            await db_router.close_all()
        except Exception:
            logger.exception("edi_db_router_close_failed")

    app.state.db_router = None
    app.state.owns_db_router = False
    app.state.tenant_resolver = None
