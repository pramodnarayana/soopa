import os
from collections.abc import Awaitable
from typing import cast

import structlog

from notification.bootstrap.container import Container

logger = structlog.get_logger(__name__)

# Instantiate and wire globally at module load time so @inject patches
# the endpoints BEFORE FastAPI inspects their signatures for Depends()
_container = Container()
_container.wire(
    modules=[
        "unified_api.adapters.inbound.http.routers.in_app_notifications_router",
        "unified_api.adapters.inbound.http.routers.notification_preferences_router",
        "unified_api.adapters.inbound.http.routers.notification_templates_router",
        "unified_api.adapters.inbound.http.routers.notification_user_preferences_router",
    ]
)


async def startup() -> None:
    """
    Starts Notification Engine background workers (Postgres Listener) and initializes DI Container.
    """
    logger.info("Notification Engine: starting up")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.warning("DATABASE_URL not set — Notification Engine will not start.")
        return

    _container.config.database_url.from_value(database_url)
    # Initialize resource lifecycle (DB engine)
    await cast(Awaitable[None], _container.init_resources())

    # Start the Postgres Listener for SSE
    # TODO(TechDebt): SSE infrastructure is deprecated and pending complete removal.
    # listener = _container.postgres_listener()
    # listener.start()


async def shutdown() -> None:
    """
    Stops Notification Engine background workers and tears down DI resources.
    """
    logger.info("Notification Engine: shutting down")

    if _container:
        # TODO(TechDebt): SSE infrastructure is deprecated and pending complete removal.
        # listener = _container.postgres_listener()
        # await listener.stop()
        await cast(Awaitable[None], _container.shutdown_resources())
