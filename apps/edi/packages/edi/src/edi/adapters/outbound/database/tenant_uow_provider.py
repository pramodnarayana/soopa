import contextlib
from collections.abc import AsyncGenerator, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from database.router import DatabaseRouterPort
from edi.ports.outbound.tenant_port import TenantPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class SqlAlchemyTenantUoWProvider:
    """
    Dependency Injection factory that abstracts away multi-tenant database shard
    resolution and yields a scoped DataPlaneUnitOfWorkPort via an injected builder.
    """

    def __init__(
        self,
        resolver: TenantPort,
        db_router: DatabaseRouterPort,
        uow_builder: Callable[[AsyncSession], DataPlaneUnitOfWorkPort],
    ) -> None:
        self._resolver = resolver
        self._db_router = db_router
        self._uow_builder = uow_builder

    async def get_uow_factory(
        self, tenant_id: str
    ) -> Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]:
        """
        Resolves the tenant's database shard and returns a parameterless async
        context manager closure that yields a DataPlaneUnitOfWorkPort.
        """
        shard_name, shard_dsn = await self._resolver.resolve_shard(tenant_id)

        @contextlib.asynccontextmanager
        async def uow_factory() -> AsyncGenerator[DataPlaneUnitOfWorkPort, None]:
            async with contextlib.aclosing(
                self._db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
            ) as session_gen:
                async for session in session_gen:
                    yield self._uow_builder(session)
                    break

        return uow_factory
