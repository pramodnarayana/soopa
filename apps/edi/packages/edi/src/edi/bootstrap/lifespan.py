"""
EDI Domain Startup and Shutdown Hooks.

These hooks initialize and tear down EDI infrastructure resources.
They are called by the Shell's lifespan (unified_api/bootstrap/lifespan.py).

Architecture note:
  - Starlette does NOT call mounted sub-app lifespans when the parent app has
    its own lifespan. All infrastructure initialization must therefore be
    delegated to the Shell's lifespan via these explicit hooks.
  - ``startup`` receives the EDI sub-app instance so that it can write
    ``db_router`` to ``edi_app.state``. This is the same state object that
    FastAPI's dependency injection layer reads from via ``request.app.state``
    when a request is dispatched into the EDI sub-app.
  - No business logic belongs here — only infrastructure wiring.
"""

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from dependency_injector import providers
from fastapi import FastAPI

from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.bootstrap.container import Container

logger = structlog.get_logger(__name__)

_db_router: DatabaseRouterPort | None = None
_edi_container: Container | None = None


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
    Initializes the EDI DatabaseRouter and attaches it to the EDI sub-app's state.

    ``app`` MUST be the EDI sub-app instance (not the Shell), because
    ``request.app`` inside EDI route handlers resolves to the sub-app.
    When called via ``EdiApiModule.startup(app, db_router)``, reuses the Shell's
    shared ``db_router`` directly.
    """
    global _db_router, _edi_container

    if db_router is not None:
        logger.info("EDI: Attaching shared DatabaseRouter from Host Shell.")
        _db_router = db_router
    else:
        logger.info("EDI: Initializing DatabaseRouter.")
        _db_router = DatabaseRouter(
            global_db_url=global_db_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            shard_overrides=shard_overrides or {},
        )
    app.state.db_router = _db_router

    resolver = TenantResolver(_db_router)
    app.state.tenant_resolver = resolver

    if hasattr(app, "container"):
        app.container.tenant_resolver.override(providers.Object(resolver))
        _edi_container = app.container

    logger.info("EDI: DatabaseRouter initialized.")


async def shutdown(app: FastAPI | None = None) -> None:
    """
    Gracefully closes the EDI DatabaseRouter connection pool and container resources.
    Called by the Shell lifespan or sub-app lifespan on application shutdown.
    """
    global _db_router, _edi_container

    container: Container | None = _edi_container
    if container is None and app is not None:
        candidate = app.__dict__.get("container")
        if isinstance(candidate, Container):
            container = candidate

    if container:
        logger.info("EDI: Shutting down as2_tester adapter.")
        try:
            tester = container.as2_tester()
            if isinstance(tester, HttpxAS2TesterAdapter):
                await tester.close()
        except Exception:
            logger.exception("edi_as2_tester_close_failed")
        _edi_container = None

    db_router: DatabaseRouterPort | None = _db_router
    if db_router is None and app is not None and "db_router" in app.state._state:
        db_router = app.state.db_router

    if db_router:
        logger.info("EDI: Shutting down DatabaseRouter.")
        try:
            await db_router.close_all()
        except Exception:
            logger.exception("edi_db_router_close_failed")
        _db_router = None
