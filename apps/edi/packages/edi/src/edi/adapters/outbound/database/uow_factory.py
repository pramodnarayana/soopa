from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import select
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.base_repository import GlobalSession
from edi.adapters.outbound.database.uow_adapter import SqlAlchemyDataPlaneUnitOfWork
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.ports.outbound.uow_factory import DataPlaneUnitOfWorkFactoryPort


class SqlAlchemyDataPlaneUnitOfWorkFactory(DataPlaneUnitOfWorkFactoryPort):
    def __init__(self, global_session: GlobalSession, db_router: DatabaseRouterPort) -> None:
        self.global_session = global_session
        self.db_router = db_router

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
        # Resolve true shard
        stmt = (
            select(DatabaseShard)
            .join(ShardRegistry, ShardRegistry.shard_id == DatabaseShard.id)
            .join(App, App.id == ShardRegistry.app_id)
            .where(ShardRegistry.tenant_id == tenant_id, App.slug == app_slug)
        )
        result = await self.global_session.execute(stmt)
        shard = result.scalar_one_or_none()

        if not shard:
            raise ValueError(f"Tenant {tenant_id} not found or no shard configured for {app_slug}")

        # Get tenant session
        async_gen_tenant = self.db_router.get_tenant_session(tenant_id, shard.name, shard.dsn)
        tenant_session = await anext(async_gen_tenant)

        # Provision Unit of Work
        uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session)
        try:
            async with uow:
                yield uow
        finally:
            await async_gen_tenant.aclose()
