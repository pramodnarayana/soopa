"""
FastAPI dependency for injecting an async SQLAlchemy session.
"""

import contextlib
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_global_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a shared Global database session for the entire HTTP request lifecycle.
    This acts as the single source of truth for global DB connections across all bounded contexts.
    """
    if not hasattr(request.app.state, "db_router") or not request.app.state.db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")
    db_router = request.app.state.db_router
    if not db_router:
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


from identity.domain.identity_context import PLATFORM_TENANT_ID

from edi.adapters.outbound.database.tenant_resolver import TenantResolver


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session per request for AS2 Server (which currently defaults to tenant 0).
    For the API service, you should use `identity.dependencies.get_tenant_session` instead.
    """
    if not hasattr(request.app.state, "db_router") or not request.app.state.db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")
    db_router = request.app.state.db_router
    if not db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    # Resolve Host Company (PLATFORM_TENANT_ID) dynamically from the Global DB
    resolver = TenantResolver(db_router=db_router)
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
