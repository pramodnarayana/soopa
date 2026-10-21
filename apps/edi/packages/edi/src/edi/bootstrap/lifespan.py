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
from database.router import DatabaseRouter
from dependency_injector import providers
from fastapi import FastAPI

from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.bootstrap.container import Container

logger = structlog.get_logger(__name__)

_db_router: DatabaseRouter | None = None
_edi_container: Container | None = None


async def startup(
    app: FastAPI,
    *,
    global_db_url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    shard_overrides: dict[str, str] | None = None,
) -> None:
    """
    Initializes the EDI DatabaseRouter and attaches it to the EDI sub-app's state.

    ``app`` MUST be the EDI sub-app instance (not the Shell), because
    ``request.app`` inside EDI route handlers resolves to the sub-app.
    The Shell calls this with the ``edi_app`` object it created, passing
    all database configuration as explicit keyword arguments (Dependency Inversion).
    The Shell is the sole composition root responsible for reading configuration.
    """
    global _db_router, _edi_container

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


async def shutdown() -> None:
    """
    Gracefully closes the EDI DatabaseRouter connection pool and container resources.
    Called by the Shell lifespan on application shutdown.
    """
    global _db_router, _edi_container

    if _edi_container:
        logger.info("EDI: Shutting down as2_tester adapter.")
        try:
            tester = _edi_container.as2_tester()
            if isinstance(tester, HttpxAS2TesterAdapter):
                await tester.close()
        except Exception:
            logger.exception("edi_as2_tester_close_failed")
        _edi_container = None

    if _db_router:
        logger.info("EDI: Shutting down DatabaseRouter.")
        await _db_router.close_all()
        _db_router = None
