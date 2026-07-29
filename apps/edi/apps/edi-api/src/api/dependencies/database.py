import contextlib
from collections.abc import AsyncGenerator

from database.base_repository import GlobalSession
from database.models import DatabaseShard, Tenant, TenantShard
from database.session import get_global_session
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.api_key import get_tenant_id_from_api_key
from api.core.uow import ControlPlaneUnitOfWork, DataPlaneUnitOfWork
from api.dependencies.auth import get_current_tenant_id

__all__ = [
    "get_global_session",
    "get_tenant_session",
    "get_control_plane_uow",
    "get_data_plane_uow",
    "get_m2m_data_plane_uow",
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
        .join(TenantShard, Tenant.id == TenantShard.tenant_id)
        .join(DatabaseShard, TenantShard.shard_id == DatabaseShard.id)
        .where(Tenant.id == tenant_id)
    )
    result = await global_session.execute(stmt)
    row = result.one_or_none()
    if not row:
        raise RuntimeError(f"Tenant {tenant_id} not found in global database")

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
    global_session: GlobalSession = Depends(get_global_session),
) -> ControlPlaneUnitOfWork:
    return ControlPlaneUnitOfWork(global_session=global_session)


async def get_data_plane_uow(
    tenant_session: AsyncSession = Depends(get_tenant_session),
) -> DataPlaneUnitOfWork:
    return DataPlaneUnitOfWork(tenant_session=tenant_session)


async def get_m2m_data_plane_uow(
    request: Request,
    tenant_id: str = Depends(get_tenant_id_from_api_key),
    global_session: GlobalSession = Depends(get_global_session),
) -> AsyncGenerator[DataPlaneUnitOfWork, None]:
    """
    Constructs a DataPlaneUnitOfWork dynamically without relying on Zitadel JWTs.
    Useful for Machine-to-Machine routes that authenticate via API keys.
    """
    async for tenant_session in get_tenant_session_for_id(request, tenant_id, global_session):
        yield DataPlaneUnitOfWork(tenant_session=tenant_session)
