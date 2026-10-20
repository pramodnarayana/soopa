"""
Enterprise Multi-Tenant Shard Resolution.

Provides caching and resolution of tenant-to-database-shard mappings
from the Global Control Plane database across any bounded context (EDI, IP, etc.).
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog
from sqlalchemy import select

from database.models.identity import Tenant
from database.models.sharding import DatabaseShard, ShardRegistry
from database.models.subscriptions import App
from database.router import DatabaseRouterPort

logger = structlog.get_logger(__name__)


class DatabaseInfrastructureError(Exception):
    """Base exception for database infrastructure operations."""


class TenantNotFoundError(DatabaseInfrastructureError, ValueError):
    """Raised when a tenant is not found or not mapped to an active shard in the Global DB."""


class TenantShardResolverPort(Protocol):
    """Abstract Port for resolving tenant shard assignments."""

    async def get_all_tenant_ids(self) -> list[str]:
        """Fetch all active tenant IDs subscribed to this application."""
        ...

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """
        Resolve a tenant_id to its dedicated database shard.

        Returns:
            tuple[str, str]: (shard_name_or_id, shard_dsn)
        """
        ...


class TenantShardResolver:
    """
    Enterprise-grade Tenant Shard Resolver with in-memory TTL caching and LRU eviction.

    Guarantees workers and gateways do not execute redundant queries against the
    Global Control Plane database for every transaction, while cleanly supporting
    hybrid multi-tenancy across bounded contexts (e.g. app_slug="edi", app_slug="ip").
    """

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        app_slug: str,
        ttl_secs: int = 300,
        max_entries: int = 1000,
    ) -> None:
        self._db_router = db_router
        self._app_slug = app_slug
        self._ttl = ttl_secs
        self._max_entries = max_entries
        self._cache: dict[str, tuple[str, str, float]] = {}

    @property
    def app_slug(self) -> str:
        return self._app_slug

    def _sweep(self, now: float) -> None:
        expired = [k for k, v in self._cache.items() if v[2] <= now]
        for k in expired:
            del self._cache[k]

        if len(self._cache) > self._max_entries:
            sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][2])
            to_evict = len(self._cache) - self._max_entries
            for k, _ in sorted_entries[:to_evict]:
                del self._cache[k]

    async def get_all_tenant_ids(self) -> list[str]:
        """Queries the Global DB for all tenants registered for this app."""
        async for session in self._db_router.get_global_session():
            stmt = (
                select(Tenant.id)
                .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                .join(App, App.id == ShardRegistry.app_id)
                .where(App.slug == self._app_slug)
            )
            result = await session.execute(stmt)
            tenant_ids = [str(t_id) for t_id in result.scalars().all()]
            logger.debug(
                "tenant_shard_resolver_fetched_all_tenants",
                app_slug=self._app_slug,
                count=len(tenant_ids),
            )
            return tenant_ids
        return []

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """
        Resolves the dedicated shard (id/name, dsn) for the given tenant_id.
        Caches results for `ttl_secs` to maintain sub-millisecond retrieval.
        """
        now = time.monotonic()
        self._sweep(now)

        tid_str = str(tenant_id)
        if tid_str in self._cache:
            shard_name, shard_dsn, expiry = self._cache[tid_str]
            if now < expiry:
                return shard_name, shard_dsn

        async for session in self._db_router.get_global_session():
            stmt = (
                select(Tenant, DatabaseShard)
                .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                .join(DatabaseShard, ShardRegistry.shard_id == DatabaseShard.id)
                .join(App, App.id == ShardRegistry.app_id)
                .where(Tenant.id == tid_str, App.slug == self._app_slug)
            )
            result = await session.execute(stmt)
            row = result.first()
            if not row:
                logger.warning(
                    "tenant_shard_not_found",
                    tenant_id=tid_str,
                    app_slug=self._app_slug,
                )
                raise TenantNotFoundError(f"Tenant {tid_str} not found in Global DB")

            _, shard_obj = row
            shard_id = str(shard_obj.id)
            shard_dsn = str(shard_obj.dsn)

            self._cache[tid_str] = (shard_id, shard_dsn, now + self._ttl)
            self._sweep(now)

            logger.info(
                "tenant_shard_resolved",
                tenant_id=tid_str,
                app_slug=self._app_slug,
                shard_id=shard_id,
            )
            return shard_id, shard_dsn

        raise TenantNotFoundError(f"Tenant {tid_str} not found in Global DB")
