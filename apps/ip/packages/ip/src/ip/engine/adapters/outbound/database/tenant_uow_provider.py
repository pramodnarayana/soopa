"""Multi-tenant Data Plane Unit of Work provider for Integration Platform gateways and workers."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.uow import SqlAlchemyIpDataPlaneUnitOfWork
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
    IpTenantResolverPort,
)

from database.router import DatabaseRouterPort
from database.uow import TenantDataPlaneUnitOfWorkProvider


class IpTenantUoWProvider(
    TenantDataPlaneUnitOfWorkProvider[IpDataPlaneUnitOfWorkPort],
    IpDataPlaneUnitOfWorkProviderPort,
):
    """Resolves a tenant's dedicated IP Data Plane shard and yields an RLS-scoped IpDataPlaneUnitOfWorkPort."""

    def __init__(
        self,
        resolver: IpTenantResolverPort,
        db_router: DatabaseRouterPort,
        storage: TieredStoragePort | None = None,
    ) -> None:
        super().__init__(
            resolver=resolver,
            db_router=db_router,
            uow_factory=lambda session: SqlAlchemyIpDataPlaneUnitOfWork(session, storage=storage),
        )
        self._ip_resolver = resolver

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return await self._ip_resolver.resolve_tenant_shard(tenant_id)


__all__ = ["IpTenantUoWProvider"]
