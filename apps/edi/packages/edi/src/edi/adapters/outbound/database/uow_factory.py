from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.ports.outbound.uow_factory import DataPlaneUnitOfWorkFactoryPort


class SqlAlchemyDataPlaneUnitOfWorkFactory(DataPlaneUnitOfWorkFactoryPort):
    def __init__(
        self,
        resolver: TenantResolver,
        db_router: DatabaseRouterPort,
        storage: StoragePort,
    ) -> None:
        self.resolver = resolver
        self.db_router = db_router
        self.storage = storage

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
        shard_name, shard_dsn = await self.resolver.resolve_shard(tenant_id)

        # Get tenant session
        async_gen_tenant = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        tenant_session = await anext(async_gen_tenant)

        # Provision Unit of Work
        uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, self.storage)
        try:
            async with uow:
                yield cast(DataPlaneUnitOfWorkPort, uow)
        finally:
            await async_gen_tenant.aclose()
