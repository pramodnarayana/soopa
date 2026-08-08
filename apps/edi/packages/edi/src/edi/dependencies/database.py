import contextlib
from collections.abc import AsyncGenerator
from typing import Annotated

from database.base_repository import GlobalSession
from database.session import get_global_session
from fastapi import Depends, Request
from platform_orm.models.identity import Tenant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from edi.adapters.uow_adapter import SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork
from edi.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
from edi.dependencies.auth import get_current_tenant_id
from edi.exceptions import TenantNotSubscribedException
from edi.ports.uow import ControlPlaneUnitOfWorkPort

__all__ = [
    "get_control_plane_uow",
    "get_data_plane_uow",
    "get_global_session",
    "get_tenant_session",
]


async def get_tenant_session_for_id(
    request: Request,
    tenant_id: str,
    global_session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """Yields an AsyncSession bound to the database shard for a given tenant."""
    db_router = getattr(request.app.state, "db_router", None)
    if not db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    stmt = (
        select(Tenant, DatabaseShard)
        .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
        .join(DatabaseShard, ShardRegistry.shard_id == DatabaseShard.id)
        .join(App, App.id == ShardRegistry.app_id)
        .where(Tenant.id == tenant_id, App.slug == "edi")
    )
    result = await global_session.execute(stmt)
    row = result.one_or_none()
    if not row:
        raise TenantNotSubscribedException(tenant_id)

    _, shard = row
    async_gen_tenant = db_router.get_tenant_session(tenant_id, shard.name, shard.dsn)
    tenant_session: AsyncSession = await async_gen_tenant.__anext__()

    try:
        yield tenant_session
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen_tenant.__anext__()


async def get_tenant_session(
    request: Request,
    tenant_id: str = Depends(get_current_tenant_id),
    global_session: AsyncSession = Depends(get_global_session),
) -> AsyncGenerator[AsyncSession, None]:
    """Yields an AsyncSession using the JWT's resolved tenant_id."""
    async for session in get_tenant_session_for_id(request, tenant_id, global_session):
        yield session


async def get_control_plane_uow(
    global_session: Annotated[GlobalSession, Depends(get_global_session)],
) -> ControlPlaneUnitOfWorkPort:
    return ControlPlaneUnitOfWork(global_session=global_session)


async def get_data_plane_uow(
    tenant_session: AsyncSession = Depends(get_tenant_session),
) -> DataPlaneUnitOfWork:
    return DataPlaneUnitOfWork(tenant_session=tenant_session)
