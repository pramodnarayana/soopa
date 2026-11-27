"""
Enterprise Database Provider

Centralized capability for provisioning SQLAlchemy AsyncEngines across the monorepo.
Guarantees identical infrastructure tuning, connection pool strategies, PgBouncer
transaction-mode safety, and URL normalization.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import exc
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.exceptions import DatabaseConfigurationError
from database.utils import normalize_to_asyncpg

logger = structlog.get_logger(__name__)


def get_async_engine(
    url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
    echo: bool = False,
    server_settings: dict[str, str] | None = None,
    statement_cache_size: int | None = None,
) -> AsyncEngine:
    """
    Creates and configures an AsyncEngine.
    Auto-converts standard postgresql URLs to asyncpg.

    Args:
        server_settings: Optional asyncpg server_settings passed as connect_args.
                         Example: {"search_path": "public"}
        statement_cache_size: Optional asyncpg prepared statement cache size.
                              Set to `0` when connecting through PgBouncer in
                              `transaction` pooling mode.
    """
    clean_url = url.strip() if url else ""
    if not clean_url:
        logger.error("database_url_validation_failed", reason="URL string is empty or unconfigured")
        raise DatabaseConfigurationError(
            "Cannot initialize database engine: database connection URL is empty or unconfigured."
        )

    try:
        normalized_url = normalize_to_asyncpg(clean_url)
    except Exception as norm_err:
        logger.error(
            "database_url_normalization_failed",
            reason=str(norm_err),
            url=clean_url,
        )
        raise DatabaseConfigurationError(
            f"Failed to normalize database connection URL: {norm_err}",
            url=clean_url,
        ) from norm_err

    connect_args: dict[str, int | dict[str, str]] = {}
    if server_settings:
        connect_args["server_settings"] = server_settings
    if statement_cache_size is not None and not normalized_url.startswith("sqlite"):
        connect_args["statement_cache_size"] = statement_cache_size

    try:
        if normalized_url.startswith("sqlite"):
            engine = (
                create_async_engine(
                    normalized_url,
                    echo=echo,
                    pool_pre_ping=pool_pre_ping,
                    connect_args=connect_args,
                )
                if connect_args
                else create_async_engine(normalized_url, echo=echo, pool_pre_ping=pool_pre_ping)
            )
        elif connect_args:
            engine = create_async_engine(
                normalized_url,
                echo=echo,
                pool_pre_ping=pool_pre_ping,
                pool_size=pool_size,
                max_overflow=max_overflow,
                connect_args=connect_args,
            )
        else:
            engine = create_async_engine(
                normalized_url,
                echo=echo,
                pool_pre_ping=pool_pre_ping,
                pool_size=pool_size,
                max_overflow=max_overflow,
            )
    except exc.ArgumentError as arg_err:
        logger.error(
            "database_url_parse_failed",
            reason=str(arg_err),
            url=clean_url,
        )
        raise DatabaseConfigurationError(
            f"Failed to parse database connection URL '{clean_url}': {arg_err}",
            url=clean_url,
        ) from arg_err

    logger.info(
        "database_engine_created",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
        statement_cache_size=statement_cache_size,
    )

    return engine


class DatabaseProvider:
    """
    Enterprise Database Provider.

    Provides a centralized connection pool (AsyncEngine) and session factory
    for the entire application lifecycle.
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
        statement_cache_size: int | None = None,
    ) -> DatabaseProvider:
        """Creates a DatabaseProvider by automatically instantiating the engine from a URL."""
        engine = get_async_engine(
            url=url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            echo=echo,
            server_settings=server_settings,
            statement_cache_size=statement_cache_size,
        )
        return cls(engine=engine)

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Context manager for acquiring a database session."""
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        """Disposes the engine connection pool. Should be called on application shutdown."""
        await self.engine.dispose()
        logger.info("database_engine_disposed")
