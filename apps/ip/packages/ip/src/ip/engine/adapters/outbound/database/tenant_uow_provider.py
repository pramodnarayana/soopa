"""Multi-tenant Data Plane Unit of Work provider for Integration Platform gateways and workers."""

from __future__ import annotations

from collections.abc import Callable

from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
    IpTenantResolverPort,
)
from sharding.application.uow_provider import TenantDataPlaneUnitOfWorkProvider
from sqlalchemy.ext.asyncio import AsyncSession

from database.router import DatabaseRouterPort
from database.types import TenantSession


class SqlAlchemyIpTenantUoWProvider(
    TenantDataPlaneUnitOfWorkProvider[IpDataPlaneUnitOfWorkPort, TenantSession],
    IpDataPlaneUnitOfWorkProviderPort,
):
    """Resolves a tenant's dedicated IP Data Plane shard and yields an RLS-scoped IpDataPlaneUnitOfWorkPort."""

    def __init__(
        self,
        resolver: IpTenantResolverPort,
        db_router: DatabaseRouterPort,
        uow_factory: Callable[[AsyncSession], IpDataPlaneUnitOfWorkPort],
    ) -> None:
        super().__init__(
            resolver=resolver,
            db_router=db_router,
            uow_factory=uow_factory,
        )
        self._ip_resolver = resolver

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return await self._ip_resolver.resolve_tenant_shard(tenant_id)


__all__ = ["SqlAlchemyIpTenantUoWProvider"]
