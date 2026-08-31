"""
Enterprise Database Routing and Provisioning.

This module provides the central multi-tenant database routing capabilities.
It enforces the Open/Closed Principle via DatabaseRouterPort, allowing the
application to depend on the interface while the infrastructure provides the
production engine manager or a transactional test double.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Protocol, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from database.provider import get_async_engine
from database.types import GlobalSession, TenantSession

logger = structlog.get_logger(__name__)


class DatabaseRouterPort(Protocol):
    """
    Interface for dynamic database routing.
    Depend on this Port in your application and tests.
    """

    def get_global_session(self) -> AsyncGenerator[GlobalSession, None]: ...

    def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]: ...

    def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]: ...

    async def get_all_shards(self) -> list[tuple[str, str]]: ...

    async def close_all(self) -> None: ...


class DatabaseRouter(DatabaseRouterPort):
    """
    Production implementation of the Database Router.
    Manages connections to the Global DB and dynamic Tenant DBs.
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
        return get_async_engine(
            url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_pre_ping=True,
            echo=False,
        )

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

        from sqlalchemy import text

        try:
            async with factory() as session:
                # Enforce Row-Level Security by injecting the tenant ID context
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                    {"tenant_id": tenant_id},
                )
                session.info["session_type"] = "tenant"
                yield cast(TenantSession, session)
        finally:
            # Note: with connection pooling, cleaning up the configuration is important if connection
            # is reused, but set_config(..., true) makes it local to the transaction.
            pass

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        """
        Yields a raw session to a shard, bypassing RLS.
        Used ONLY by background sweeping and replication jobs.
        """
        engine = await self.get_engine(shard_key, shard_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            session.info["session_type"] = "tenant"
            yield cast(TenantSession, session)

    async def get_all_shards(self) -> list[tuple[str, str]]:
        """
        Retrieves all active shards (key, dsn) from the global database.
        """
        from sqlalchemy import select
        from ucp_models.infrastructure import DatabaseShard

        from database.constants import DatabaseShardStatus

        # Dynamically query the active database shards registered in the control plane
        async for session in self.get_global_session():
            result = await session.execute(
                select(DatabaseShard.id, DatabaseShard.dsn).where(
                    DatabaseShard.status == DatabaseShardStatus.ACTIVE
                )
            )
            return [(row.id, row.dsn) for row in result]
        return []

    async def close_all(self) -> None:
        """
        Closes all cached engine connection pools.
        """
        async with self._engine_lock:
            for engine in self._engines.values():
                await engine.dispose()
            self._engines.clear()
            logger.info("Closed all DatabaseRouter connection pools.")
