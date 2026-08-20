import contextlib
from collections.abc import AsyncGenerator, Callable

from config.settings import AppSettings
from database.connection import DatabaseRouter
from pipeline.adapters.storage import S3StorageClient
from pipeline.ports.unit_of_work import DataPlaneUnitOfWork

from worker.adapters.outbound.database.data_plane_unit_of_work import (
    SqlAlchemyDataPlaneUnitOfWork,
)
from worker.core.tenant_resolver import TenantResolver


class TenantUowProvider:
    """
    Dependency Injection factory that abstracts away the complex multi-tenant
    database shard resolution. It provides a clean, scoped Unit of Work
    factory without leaking database connection logic to Application Services.
    """

    def __init__(
        self,
        resolver: TenantResolver,
        db_router: DatabaseRouter,
        settings: AppSettings,
        s3_bucket: str,
        aws_endpoint: str | None,
    ) -> None:
        self._resolver = resolver
        self._db_router = db_router
        self._settings = settings
        self._storage = S3StorageClient(bucket_name=s3_bucket, endpoint_url=aws_endpoint)

    async def get_uow_factory(
        self, tenant_id: str
    ) -> Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWork]]:
        """
        Resolves the tenant's database shard and returns a parameterless async
        context manager closure that yields a DataPlaneUnitOfWork.
        """
        shard_name, shard_dsn = await self._resolver.resolve(tenant_id)

        @contextlib.asynccontextmanager
        async def uow_factory() -> AsyncGenerator[DataPlaneUnitOfWork, None]:
            async with contextlib.aclosing(
                self._db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
            ) as session_gen:
                async for session in session_gen:
                    yield SqlAlchemyDataPlaneUnitOfWork(
                        session=session, settings=self._settings, storage=self._storage
                    )
                    break

        return uow_factory
