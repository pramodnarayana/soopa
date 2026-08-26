"""
Dynamic Async SQLAlchemy session provisioner for Hybrid Multi-Tenancy.

This adapter resolves which database a tenant should connect to,
manages the connection pools (engines) efficiently, and enforces
Row-Level Security (RLS).
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import cast

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from database.provider import get_async_engine
from edi.adapters.outbound.database.base_repository import GlobalSession, TenantSession

logger = structlog.get_logger(__name__)


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
        self._engine_lock = asyncio.Lock()

        # Initialize the global control plane engine
        self._engines["global"] = self._create_engine(self._global_db_url)
        logger.info("Initialized DatabaseRouter with global connection pool.")

    def _create_engine(self, url: str) -> AsyncEngine:
        # Enterprise-grade compatibility: transparently handle standard Postgres DSNs
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        return get_async_engine(url)

    async def get_engine(self, db_key: str, url: str | None = None) -> AsyncEngine:
        """
        Retrieves or creates an AsyncEngine for a specific database shard.
        """
        if db_key not in self._engines:
            async with self._engine_lock:
                if db_key not in self._engines:
                    if not url:
                        raise ValueError(f"Engine for {db_key} not found and no URL provided.")
                    self._engines[db_key] = self._create_engine(url)
                    logger.info(
                        "Created new connection pool for database shard: {db_key}", db_key=db_key
                    )
        return self._engines[db_key]

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        """
        Yields a session connected to the global control plane.
        """
        engine = await self.get_engine("global")
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            session.info["session_type"] = "global"
            yield cast(GlobalSession, session)

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        """
        Yields a session connected to a specific tenant's shard.
        Crucially, it sets the PostgreSQL Row-Level Security (RLS) variable
        for the transaction context.
        """
        engine = await self.get_engine(shard_key, shard_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with factory() as session:
            session.info["session_type"] = "tenant"
            # Enforce Row-Level Security isolation
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            yield cast(TenantSession, session)

    async def close_all(self) -> None:
        """
        Cleanly closes all connection pools.
        """
        for key, engine in self._engines.items():
            await engine.dispose()
            logger.info("Closed connection pool for {key}", key=key)
        self._engines.clear()

    async def get_all_shards(self) -> list[tuple[str, str]]:
        """
        Retrieves all registered database shards.
        Falls back to the configured default_shard_url if no shards are registered
        in the Global Control Plane.
        """
        from sqlalchemy import select
        from ucp_models.infrastructure import DatabaseShard

        from edi.config.settings import get_settings

        async with aclosing(self.get_global_session()) as sessions:
            async for session in sessions:
                res = await session.execute(select(DatabaseShard))
                shards = res.scalars().all()
                if not shards:
                    default_url = get_settings().database.default_shard_url
                    if default_url:
                        logger.info("no_database_shards_found_using_default_shard_url")
                        return [("shard_1", default_url)]
                return [(str(shard.name), str(shard.dsn)) for shard in shards]
        return []
