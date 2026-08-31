"""
Enterprise Database Provider

Centralized capability for provisioning SQLAlchemy AsyncEngines across the monorepo.
Guarantees identical infrastructure tuning, connection pool strategies, and URL normalization.
"""

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

    kwargs: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": pool_pre_ping,
    }
    if not url.startswith("sqlite"):
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow

    engine = create_async_engine(url, **kwargs)

    logger.info(
        "database_engine_created",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )

    return engine


class DatabaseProvider:
    """
    Enterprise Database Provider.

    Provides a centralized connection pool (AsyncEngine) and session factory
    for the entire application lifecycle. Ensures that only one engine is created
    per provider instance.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @classmethod
    def from_url(
        cls,
        url: str,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_pre_ping: bool = True,
        echo: bool = False,
    ) -> "DatabaseProvider":
        """
        Creates a DatabaseProvider by automatically instantiating the engine from a URL.
        """
        engine = get_async_engine(
            url=url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            echo=echo,
        )
        return cls(engine=engine)

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Context manager for acquiring a database session.
        """
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        """
        Disposes the engine connection pool. Should be called on application shutdown.
        """
        await self.engine.dispose()
        logger.info("database_engine_disposed")
