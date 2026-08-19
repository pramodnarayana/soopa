"""
UCP Domain Startup and Shutdown Hooks.

These are pure async functions that start and stop UCP background workers.
They accept NO ``app`` parameter — UCP domain workers must not hold a reference
to the Shell application instance.

Architecture note:
  - These hooks are called by the Shell's lifespan (unified_api/bootstrap/lifespan.py).
  - The Shell owns the lifecycle; UCP exposes discrete start/stop operations.
  - This follows the Dependency Inversion Principle: the Shell depends on UCP's
    hooks, but UCP does not depend on (or know about) the Shell.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog

logger = structlog.get_logger(__name__)


async def startup() -> None:
    """
    Called by the Shell lifespan on application startup.
    (API is now 100% pure - no background workers running here).
    """
    logger.info("ucp_api_startup")


async def shutdown() -> None:
    """
    Called by the Shell lifespan on application shutdown.
    """
    logger.info("ucp_api_shutdown")


from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await startup()
    yield
    await shutdown()
