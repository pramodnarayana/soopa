from database.provider import DatabaseProvider
from dependency_injector import providers
from starlette.routing import Mount
from ucp.bootstrap.config import get_settings

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
  - Startup order: UCP workers → EDI infrastructure.
  - Shutdown order (reverse): EDI infrastructure → UCP workers.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from edi.bootstrap.lifespan import shutdown as edi_shutdown
from edi.bootstrap.lifespan import startup as edi_startup
from fastapi import FastAPI
from ucp.bootstrap.lifespan import shutdown as ucp_shutdown
from ucp.bootstrap.lifespan import startup as ucp_startup

logger = structlog.get_logger(__name__)


from notification.bootstrap.lifespan import shutdown as notification_shutdown
from notification.bootstrap.lifespan import startup as notification_startup


@asynccontextmanager
async def shell_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Shell application lifespan context manager.

    Startup order:
      1. UCP background workers (outbox sweeper, event listener).
      2. Notification Engine background workers.
      3. EDI DatabaseRouter — attached to the EDI sub-app's state so that
         ``request.app.state.db_router`` resolves correctly inside EDI routes.

    Shutdown order (reverse):
      1. EDI DatabaseRouter.
      2. Notification Engine background workers.
      3. UCP background workers.
    """
    # Retrieve the EDI sub-app from the Shell's mounted routes.
    # The Shell created edi_app and passed it to app.mount("/", edi_app).
    # We locate it here to pass to the EDI startup hook so it can attach
    # db_router to the correct app.state object.

    edi_app = next(
        (route.app for route in app.routes if isinstance(route, Mount) and route.path == ""),
        None,
    )
    if edi_app is None or not isinstance(edi_app, FastAPI):
        raise RuntimeError(
            "EDI sub-app not found or is not a FastAPI instance. "
            "Ensure app.mount('/', edi_app) is called before Shell startup."
        )

    settings = get_settings()
    db_provider = DatabaseProvider.from_url(settings.database_url)
    app.state.db_provider = db_provider
    edi_app.state.db_provider = db_provider
    ucp_container = app.state.ucp_container
    ucp_container.db_provider.override(providers.Object(db_provider))

    # Nested try/finally blocks ensure cleanup runs in reverse order
    # and only for services that have actually started.
    logger.info("Shell startup: initializing UCP domain workers.")
    await ucp_startup()
    try:
        logger.info("Shell startup: initializing Notification Engine workers.")
        await notification_startup()
        try:
            logger.info("Shell startup: initializing EDI domain infrastructure.")
            await edi_startup(edi_app)
            try:
                # Normal operation
                yield
            finally:
                # EDI started successfully, always clean it up
                logger.info("Shell shutdown: stopping EDI domain infrastructure.")
                await edi_shutdown()
        finally:
            # Notification Engine started successfully, always clean it up
            logger.info("Shell shutdown: stopping Notification Engine workers.")
            await notification_shutdown()
    finally:
        # UCP started successfully, always clean it up
        logger.info("Shell shutdown: stopping UCP domain workers.")
        await ucp_shutdown()
        logger.info("Shell shutdown: closing DatabaseProvider.")
        await db_provider.close()
