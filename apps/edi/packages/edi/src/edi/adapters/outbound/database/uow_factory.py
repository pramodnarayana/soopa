from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from database.router import DatabaseRouterPort
from edi.ports.outbound.tenant_port import TenantPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.ports.outbound.uow_factory import DataPlaneUnitOfWorkFactoryPort


class SqlAlchemyDataPlaneUnitOfWorkFactory(DataPlaneUnitOfWorkFactoryPort):
    def __init__(
        self,
        resolver: TenantPort,
        db_router: DatabaseRouterPort,
        uow_builder: Callable[[AsyncSession], DataPlaneUnitOfWorkPort],
    ) -> None:
        self.resolver = resolver
        self.db_router = db_router
        self._uow_builder = uow_builder

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
        shard_name, shard_dsn = await self.resolver.resolve_shard(tenant_id)

        async_gen_tenant = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        tenant_session = await anext(async_gen_tenant)

        uow = self._uow_builder(tenant_session)
        try:
            async with uow:
                yield uow
        finally:
            await async_gen_tenant.aclose()
