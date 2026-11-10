from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from sharding.application.uow_provider import TenantDataPlaneUnitOfWorkProvider
from sqlalchemy.ext.asyncio import AsyncSession

from database.router import DatabaseRouterPort
from database.types import TenantSession
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
        self._uow_provider: TenantDataPlaneUnitOfWorkProvider[
            DataPlaneUnitOfWorkPort, TenantSession
        ] = TenantDataPlaneUnitOfWorkProvider(
            resolver=resolver,
            db_router=db_router,
            uow_factory=uow_builder,
        )
        self.resolver = resolver
        self.db_router = db_router

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
        _ = app_slug
        shard_name, shard_dsn = await self._uow_provider.resolve_shard(tenant_id)
        async with self._uow_provider.get_data_plane_uow(tenant_id, shard_name, shard_dsn) as uow:
            yield uow
