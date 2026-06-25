"""
Dynamic Async SQLAlchemy session provisioner for Hybrid Multi-Tenancy.

This adapter resolves which database a tenant should connect to,
manages the connection pools (engines) efficiently, and enforces
Row-Level Security (RLS).
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class DatabaseRouter:
    """
    Manages connections to the Global DB and dynamic Tenant DBs.
    Follows DI principles: this should be instantiated once per application lifecycle
    and injected, rather than used as a global mutable singleton.
    """

    def __init__(self, global_db_url: str, pool_size: int = 10, max_overflow: int = 20):
        self._global_db_url = global_db_url
        self._pool_size = pool_size
        self._max_overflow = max_overflow

        # Cache for tenant engines to avoid recreation
        self._engines: dict[str, AsyncEngine] = {}

        # Initialize the global control plane engine
        self._engines["global"] = self._create_engine(self._global_db_url)
        logger.info("Initialized DatabaseRouter with global connection pool.")

    def _create_engine(self, url: str) -> AsyncEngine:
        return create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
        )

    def get_engine(self, db_key: str, url: str | None = None) -> AsyncEngine:
        """
        Retrieves or creates an AsyncEngine for a specific database shard.
        """
        if db_key not in self._engines:
            if not url:
                raise ValueError(f"Engine for {db_key} not found and no URL provided.")
            self._engines[db_key] = self._create_engine(url)
            logger.info(f"Created new connection pool for database shard: {db_key}")
        return self._engines[db_key]

    async def get_global_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Yields a session connected to the Global Control Plane DB.
        """
        factory = async_sessionmaker(
            self.get_engine("global"),
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            yield session

    async def get_tenant_session(
        self, tenant_id: int, shard_key: str, shard_url: str
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        Yields a session connected to a specific tenant's shard.
        Crucially, it sets the PostgreSQL Row-Level Security (RLS) variable
        for the transaction context.
        """
        engine = self.get_engine(shard_key, shard_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with factory() as session:
            # Enforce Row-Level Security isolation
            # PostgreSQL does not support bind parameters for SET commands,
            # so we must format the string directly. tenant_id is an integer so it's safe.
            await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id}'"))
            yield session

    async def close_all(self) -> None:
        """
        Cleanly closes all connection pools.
        """
        for key, engine in self._engines.items():
            await engine.dispose()
            logger.info(f"Closed connection pool for {key}")
        self._engines.clear()
