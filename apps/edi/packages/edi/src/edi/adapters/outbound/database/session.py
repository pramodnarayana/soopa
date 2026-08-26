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
    db_router = getattr(request.app.state, "db_router", None)
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


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session per request for AS2 Server (which currently defaults to tenant 0).
    For the API service, you should use `identity.dependencies.get_tenant_session` instead.
    """
    db_router = getattr(request.app.state, "db_router", None)
    if not db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    # Resolve Host Company (Tenant 0) dynamically from the Global DB
    from sqlalchemy import select
    from ucp_models.infrastructure import DatabaseShard

    from database.models.identity import Tenant

    global_gen = db_router.get_global_session()
    global_session = await global_gen.__anext__()
    try:
        stmt = select(Tenant, DatabaseShard).join(DatabaseShard).where(Tenant.id == 0)
        result = await global_session.execute(stmt)
        row = result.first()
        if not row:
            raise RuntimeError("Host tenant (Tenant 0) not found in Global DB")
        tenant_obj, shard_obj = row
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await global_gen.__anext__()

    async_gen = db_router.get_tenant_session(
        tenant_id=int(tenant_obj.id),
        shard_key=str(shard_obj.name),
        shard_url=str(shard_obj.dsn),
    )

    session = await async_gen.__anext__()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
