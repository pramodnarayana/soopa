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

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.config.settings import get_settings

logger = structlog.get_logger(__name__)

_db_router: DatabaseRouter | None = None


async def startup(app: FastAPI) -> None:
    """
    Initializes the EDI DatabaseRouter and attaches it to the EDI sub-app's state.

    ``app`` MUST be the EDI sub-app instance (not the Shell), because
    ``request.app`` inside EDI route handlers resolves to the sub-app.
    The Shell calls this with the ``edi_app`` object it created.
    """
    global _db_router

    settings = get_settings()
    logger.info("EDI: Initializing DatabaseRouter.")
    _db_router = DatabaseRouter(
        settings.database.global_url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )
    # Attach to the EDI sub-app's state so request.app.state.db_router resolves correctly.
    app.state.db_router = _db_router
    logger.info("EDI: DatabaseRouter initialized.")


async def shutdown() -> None:
    """
    Gracefully closes the EDI DatabaseRouter connection pool.
    Called by the Shell lifespan on application shutdown.
    """
    global _db_router

    if _db_router:
        logger.info("EDI: Shutting down DatabaseRouter.")
        await _db_router.close_all()
        _db_router = None


@asynccontextmanager
async def edi_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Standalone lifespan context manager for the EDI application.
    This is used when the EDI app is run independently (or tested via TestClient).
    When mounted as a sub-app in the Modular Monolith, Starlette ignores this,
    and the Shell's lifespan calls the startup/shutdown hooks directly.
    """
    await startup(app)
    yield
    await shutdown()
