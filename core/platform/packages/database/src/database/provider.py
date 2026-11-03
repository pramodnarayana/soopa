"""
Enterprise Database Provider

Centralized capability for provisioning SQLAlchemy AsyncEngines and LISTEN/NOTIFY
connections across the monorepo. Guarantees identical infrastructure tuning,
connection pool strategies, and URL normalization.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.listener import NotifyListenerConnectionPort, connect_notify_listener
from database.utils import normalize_to_asyncpg

logger = structlog.get_logger(__name__)


def get_async_engine(
    url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
    echo: bool = False,
    server_settings: dict[str, str] | None = None,
) -> AsyncEngine:
    """
    Creates and configures an AsyncEngine.
    Auto-converts standard postgresql URLs to asyncpg.

    Args:
        server_settings: Optional asyncpg server_settings passed as connect_args.
                         Use this to explicitly enforce settings like search_path
                         instead of relying on implicit PostgreSQL defaults.
                         Example: {"search_path": "public"}
    """
    url = normalize_to_asyncpg(url)
    connect_args: dict[str, dict[str, str]] = (
        {"server_settings": server_settings} if server_settings else {}
    )

    if url.startswith("sqlite"):
        engine = (
            create_async_engine(
                url,
                echo=echo,
                pool_pre_ping=pool_pre_ping,
                connect_args=connect_args,
            )
            if connect_args
            else create_async_engine(url, echo=echo, pool_pre_ping=pool_pre_ping)
        )
    elif connect_args:
        engine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=pool_pre_ping,
            pool_size=pool_size,
            max_overflow=max_overflow,
            connect_args=connect_args,
        )
    else:
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


class DatabaseProvider:
    """
    Enterprise Database Provider.

    Provides a centralized connection pool (AsyncEngine), session factory, and
    LISTEN/NOTIFY connection factory for the entire application lifecycle.
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
        server_settings: dict[str, str] | None = None,
    ) -> DatabaseProvider:
        """
        Creates a DatabaseProvider by automatically instantiating the engine from a URL.
        """
        engine = get_async_engine(
            url=url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            echo=echo,
            server_settings=server_settings,
        )
        return cls(engine=engine)

    @staticmethod
    async def connect_listener(url: str) -> NotifyListenerConnectionPort:
        """Opens a dedicated PostgreSQL LISTEN/NOTIFY connection."""
        return await connect_notify_listener(url)

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
