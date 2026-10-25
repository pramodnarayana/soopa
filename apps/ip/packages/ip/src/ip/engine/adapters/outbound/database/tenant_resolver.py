"""Integration Platform Tenant Shard Resolver."""

from __future__ import annotations

from ip.engine.domain.exceptions import Result, TenantShardNotFoundError

from database.router import DatabaseRouterPort
from database.tenant_shard_resolver import TenantNotFoundError, TenantShardResolver

IP_APP_SLUG = "ip"

__all__ = ["IP_APP_SLUG", "IpTenantResolver", "TenantNotFoundError", "TenantResolver"]


class IpTenantResolver(TenantShardResolver):
    """IP-specific TenantShardResolver resolving dedicated Data Plane shards (app_slug='ip')."""

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        ttl_secs: int = 300,
        max_entries: int = 1000,
    ) -> None:
        super().__init__(
            db_router=db_router,
            app_slug=IP_APP_SLUG,
            ttl_secs=ttl_secs,
            max_entries=max_entries,
        )
        self.db_router = db_router

    async def resolve_tenant_shard(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        """First-Class Error Handling wrapper around resolve_shard without raising exceptions."""
        try:
            shard_id, shard_dsn = await self.resolve_shard(tenant_id)
            return Result.ok((shard_id, shard_dsn))
        except TenantNotFoundError:
            return Result.fail(TenantShardNotFoundError.for_tenant(tenant_id))


TenantResolver = IpTenantResolver
