"""Multi-tenant Data Plane Unit of Work provider for Integration Platform gateways and workers."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from ip.engine.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.ports.outbound.uow import DataPlaneUnitOfWorkPort, DataPlaneUnitOfWorkProviderPort

from database.router import DatabaseRouterPort


class IpTenantUoWProvider(DataPlaneUnitOfWorkProviderPort):
    """Resolves a tenant's dedicated IP Data Plane shard and yields an RLS-scoped DataPlaneUnitOfWorkPort."""

    def __init__(
        self,
        resolver: IpTenantResolver,
        db_router: DatabaseRouterPort,
    ) -> None:
        self._resolver = resolver
        self._db_router = db_router

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return await self._resolver.resolve_tenant_shard(tenant_id)

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
        """Yields an RLS-isolated DataPlaneUnitOfWorkPort bound to the resolved IP shard."""
        async with contextlib.aclosing(
            self._db_router.get_tenant_session(tenant_id, shard_id, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session=session)
                async with uow:
                    yield uow
                break


__all__ = ["IpTenantUoWProvider"]
