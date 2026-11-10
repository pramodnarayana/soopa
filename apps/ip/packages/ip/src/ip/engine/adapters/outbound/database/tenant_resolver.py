"""Integration Platform Tenant Shard Resolver."""

from __future__ import annotations

from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from sharding.domain.constants import ShardResolutionStatus
from sharding.domain.exceptions import TenantNotFoundError
from sharding.provider import SqlAlchemyTenantShardResolver

from database.router import DatabaseRouterPort

IP_APP_SLUG = "ip"

__all__ = ["IP_APP_SLUG", "SqlAlchemyIpTenantResolver", "TenantNotFoundError"]


class SqlAlchemyIpTenantResolver(SqlAlchemyTenantShardResolver):
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
        """First-Class Error Handling resolution via `resolve_tenant_endpoint` without exceptions."""
        outcome = await self.resolve_tenant_endpoint(tenant_id)
        if outcome.status == ShardResolutionStatus.NOT_FOUND or outcome.endpoint is None:
            return Result.fail(TenantShardNotFoundError.for_tenant(tenant_id))
        return Result.ok((outcome.endpoint.shard_id, outcome.endpoint.writer_dsn))
