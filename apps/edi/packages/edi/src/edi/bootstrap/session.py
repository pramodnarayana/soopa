"""
FastAPI session dependencies assembled at the EDI bootstrap boundary.
"""

import contextlib
from collections.abc import AsyncGenerator

from database.router import DatabaseRouterPort
from fastapi import Request
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy.ext.asyncio import AsyncSession

from edi.ports.outbound.tenant_port import TenantPort


async def get_global_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a shared Global database session for the entire HTTP request lifecycle.
    This acts as the single source of truth for global DB connections across all bounded contexts.
    """
    db_router: DatabaseRouterPort | None = request.app.state.db_router
    if db_router is None:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    async_gen = db_router.get_global_session()
    global_session: AsyncSession = await async_gen.__anext__()
    try:
        yield global_session
        await global_session.commit()
    except Exception:
        await global_session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session per request for AS2 Server (which defaults to PLATFORM_TENANT_ID).
    """
    db_router: DatabaseRouterPort | None = request.app.state.db_router
    if db_router is None:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    resolver: TenantPort | None = request.app.state.tenant_resolver
    if resolver is None:
        raise RuntimeError("TenantResolver not initialized in app state")

    try:
        shard_id, shard_dsn = await resolver.resolve_shard(PLATFORM_TENANT_ID)
    except ValueError as e:
        raise RuntimeError("Host tenant not found in Global DB") from e

    async_gen = db_router.get_tenant_session(
        tenant_id=PLATFORM_TENANT_ID,
        shard_key=shard_id,
        shard_url=shard_dsn,
    )

    session = await async_gen.__anext__()
    try:
        yield session
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
