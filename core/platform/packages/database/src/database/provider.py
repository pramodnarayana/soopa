"""
Enterprise Database Provider

Centralized capability for provisioning SQLAlchemy AsyncEngines across the monorepo.
Guarantees identical infrastructure tuning, connection pool strategies, and URL normalization.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger(__name__)


def get_async_engine(
    url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> AsyncEngine:
    """
    Creates and configures an AsyncEngine.
    Auto-converts standard postgresql URLs to asyncpg.
    """
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )

    logger.info(
        "database_engine_created",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )

    return engine
