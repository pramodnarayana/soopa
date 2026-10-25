"""Database and Unit of Work dependencies for Integration Platform HTTP routers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from database.router import DatabaseRouterPort
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.dependencies import get_db_session

from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)


async def get_ip_global_session(
    session: AsyncSession = Depends(get_db_session),
) -> AsyncGenerator[AsyncSession, None]:
    """Yields the request-scoped Control Plane GlobalSession shared with perimeter guards."""
    yield session


def get_ip_control_plane_uow(
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> IpControlPlaneUnitOfWorkPort:
    """Resolves an IpControlPlaneUnitOfWorkPort bound to the request Control Plane session."""
    return SqlAlchemyIpControlPlaneUnitOfWork(global_session=global_session)


def get_ip_data_plane_uow_provider(request: Request) -> IpDataPlaneUnitOfWorkProviderPort:
    """Resolves the IpDataPlaneUnitOfWorkProviderPort bound to the centralized DatabaseRouter and IpTenantResolver."""
    state = request.app.state
    db_router: DatabaseRouterPort = state.db_router
    resolver: IpTenantResolver = (
        state.ip_tenant_resolver
        if hasattr(state, "ip_tenant_resolver") and state.ip_tenant_resolver is not None
        else IpTenantResolver(db_router)
    )
    return IpTenantUoWProvider(resolver=resolver, db_router=db_router)


__all__ = [
    "get_ip_control_plane_uow",
    "get_ip_data_plane_uow_provider",
    "get_ip_global_session",
]
