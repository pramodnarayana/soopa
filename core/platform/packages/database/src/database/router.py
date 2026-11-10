"""
Enterprise Database Routing and Provisioning.

Provides centralized multi-tenant and cellular Pod database routing with
compile-time segregated Write (`DatabaseRouterPort`) and Read (`DatabaseReadRouterPort`)
interfaces, PgBouncer transaction-mode safety, per-Pod connection pool bulkheads,
and `SQLSTATE 25001`-safe read-only RLS session initialization.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast, runtime_checkable

import structlog
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from database.constants import DatabaseShardStatus
from database.models.sharding import DatabaseShard, ShardRegistry
from database.models.subscriptions import App
from database.provider import get_async_engine
from database.types import GlobalSession, TenantReadSession, TenantSession
from database.utils import shard_connect_args

logger = structlog.get_logger(__name__)


@runtime_checkable
class DatabaseRouterPort(Protocol):
    """Interface for dynamic Control Plane and Primary Writer Data Plane routing."""

    def get_global_session(self) -> AsyncGenerator[GlobalSession, None]: ...

    def global_session_scope(self) -> AbstractAsyncContextManager[GlobalSession]: ...

    def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]: ...

    def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]: ...

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]: ...

    async def close_all(self) -> None: ...


@runtime_checkable
class DatabaseReadRouterPort(Protocol):
    """Segregated CQRS Read Port yielding `TenantReadSession` bound to Read Replicas."""

    def get_tenant_read_session(
        self,
        tenant_id: str,
        pool_key: str,
        target_dsn: str,
    ) -> AsyncGenerator[TenantReadSession, None]: ...


class DatabaseRouter(DatabaseRouterPort, DatabaseReadRouterPort):
    """
    Production implementation of the Database Router.

    Maintains isolated bulkhead connection pools per `(shard_id, role)` for both
    Primary Writers and Read Replicas, enforcing PostgreSQL RLS and PgBouncer safety.
    """

    def __init__(
        self,
        global_db_url: str,
        pool_size: int = 10,
        max_overflow: int = 20,
        shard_overrides: dict[str, str] | None = None,
        statement_cache_size: int | None = None,
    ) -> None:
        self._global_db_url = global_db_url
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._statement_cache_size = statement_cache_size
        self._shard_overrides = {k.lower(): v for k, v in (shard_overrides or {}).items()}

        self._engines: dict[str, AsyncEngine] = {}
        self._engine_lock = asyncio.Lock()

        self._engines["global"] = self._create_engine(self._global_db_url)
        logger.info(
            "database_router_initialized",
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            statement_cache_size=self._statement_cache_size,
        )

    def _resolve_dsn(self, default_dsn: str, *keys: str | None) -> str:
        """Resolve a DSN by checking case-insensitive environment overrides."""
        for key in keys:
            if key and key.lower() in self._shard_overrides:
                return self._shard_overrides[key.lower()]
        return default_dsn

    def _create_engine(self, url: str) -> AsyncEngine:
        return get_async_engine(
            url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_pre_ping=True,
            echo=False,
            statement_cache_size=self._statement_cache_size,
        )

    def _create_shard_engine(self, url: str) -> AsyncEngine:
        """Create an isolated bulkhead engine for a dedicated Pod Writer or Reader."""
        return get_async_engine(
            url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_pre_ping=True,
            echo=False,
            server_settings=shard_connect_args()["server_settings"],
            statement_cache_size=self._statement_cache_size,
        )

    async def get_engine(self, db_key: str, url: str | None = None) -> AsyncEngine:
        """Retrieve or lazily provision a per-Pod / per-role bulkhead `AsyncEngine`."""
        if db_key not in self._engines:
            async with self._engine_lock:
                if db_key not in self._engines:
                    if not url:
                        raise ValueError(f"Engine for {db_key} not found and no URL provided.")
                    self._engines[db_key] = self._create_shard_engine(url)
                    logger.info("database_shard_pool_created", db_key=db_key)
        return self._engines[db_key]

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        """Yield a session connected to the Global Control Plane."""
        engine = await self.get_engine("global")
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            session.info["session_type"] = "global"
            yield cast(GlobalSession, session)

    @asynccontextmanager
    async def global_session_scope(self) -> AsyncIterator[GlobalSession]:
        """Async context manager yielding a `GlobalSession`."""
        async for session in self.get_global_session():
            yield session

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        """Yield a Primary Writer session scoped to `tenant_id` via PostgreSQL RLS."""
        resolved_url = self._resolve_dsn(shard_url, shard_key)
        engine = await self.get_engine(shard_key, resolved_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with factory() as session:
            await session.execute(
                text("SELECT set_config('platform.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            session.info["session_type"] = "tenant"
            yield cast(TenantSession, session)

    async def get_tenant_read_session(
        self,
        tenant_id: str,
        pool_key: str,
        target_dsn: str,
    ) -> AsyncGenerator[TenantReadSession, None]:
        """
        Yield a strictly read-only RLS session bound to a Read Replica or fallback pool.

        PostgreSQL Engine Invariant (`SQLSTATE 25001` Prevention):
        `SET LOCAL TRANSACTION READ ONLY` MUST execute as the very first statement in
        the transaction before `SELECT set_config(...)` runs.
        """
        base_shard_key = pool_key.split(":", maxsplit=1)[0]
        resolved_url = self._resolve_dsn(target_dsn, pool_key, base_shard_key)
        engine = await self.get_engine(pool_key, resolved_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL TRANSACTION READ ONLY"))
            await session.execute(
                text("SELECT set_config('platform.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            session.info["session_type"] = "tenant_read"
            yield cast(TenantReadSession, session)

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        """Yield a raw Pod session bypassing RLS for background sweepers and relays."""
        resolved_url = self._resolve_dsn(shard_url, shard_key)
        engine = await self.get_engine(shard_key, resolved_url)
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            session.info["session_type"] = "tenant"
            yield cast(TenantSession, session)

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        """Retrieve all active shards `(shard_id, dsn)` from the Global Control Plane."""
        async for session in self.get_global_session():
            if app_slug:
                escaped_slug = (
                    app_slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                stmt = (
                    select(DatabaseShard.id, DatabaseShard.name, DatabaseShard.dsn)
                    .outerjoin(ShardRegistry, DatabaseShard.id == ShardRegistry.shard_id)
                    .outerjoin(App, ShardRegistry.app_id == App.id)
                    .where(
                        DatabaseShard.status.in_(
                            (
                                DatabaseShardStatus.ACTIVE.value,
                                DatabaseShardStatus.REPLICATING.value,
                            )
                        ),
                        or_(
                            App.slug == app_slug,
                            DatabaseShard.id.ilike(f"{escaped_slug}\\_%", escape="\\"),
                        ),
                    )
                    .distinct()
                )
            else:
                stmt = select(DatabaseShard.id, DatabaseShard.name, DatabaseShard.dsn).where(
                    DatabaseShard.status.in_(
                        (
                            DatabaseShardStatus.ACTIVE.value,
                            DatabaseShardStatus.REPLICATING.value,
                        )
                    )
                )
            result = await session.execute(stmt)
            shards: list[tuple[str, str]] = []
            for row in result:
                dsn = self._resolve_dsn(row.dsn, row.id, row.name)
                shards.append((row.id, dsn))
            return shards
        return []

    async def close_all(self) -> None:
        """Dispose all cached engine connection pools."""
        async with self._engine_lock:
            for engine in self._engines.values():
                await engine.dispose()
            self._engines.clear()
            logger.info("database_router_pools_closed")
