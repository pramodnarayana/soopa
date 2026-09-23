import contextlib
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast

import structlog
from dependency_injector.wiring import Provide, inject
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort, DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

from database.types import GlobalSession
from edi.adapters.outbound.database.session import get_global_session
from edi.bootstrap.container import Container
from edi.exceptions import TenantNotSubscribedException
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id

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
    db_router = request.app.state.db_router
    tenant_resolver = request.app.state.tenant_resolver

    if not db_router or not tenant_resolver:
        raise RuntimeError("DatabaseRouter or TenantResolver not initialized in app state")

    try:
        shard_name, shard_dsn = await tenant_resolver.resolve_shard(tenant_id)
    except ValueError as e:
        logger.exception(
            "tenant_subscription_guard_failed",
            tenant_id=tenant_id,
            app_slug="edi",
            reason=str(e),
        )
        raise TenantNotSubscribedException(tenant_id)

    async_gen_tenant = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
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


@inject
async def get_control_plane_uow(
    global_session: Annotated[GlobalSession, Depends(get_global_session)],
    cp_uow_factory: Any = Depends(Provide[Container.cp_uow.provider]),
) -> ControlPlaneUnitOfWorkPort:
    return cast(ControlPlaneUnitOfWorkPort, cp_uow_factory(global_session=global_session))


@inject
async def get_data_plane_uow(
    tenant_session: AsyncSession = Depends(get_tenant_session),
    dp_uow_factory: Any = Depends(Provide[Container.dp_uow.provider]),
) -> DataPlaneUnitOfWorkPort:
    return cast(DataPlaneUnitOfWorkPort, dp_uow_factory(tenant_session=tenant_session))
