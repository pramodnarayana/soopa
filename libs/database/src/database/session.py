"""
FastAPI dependency for injecting an async SQLAlchemy session.
"""

import contextlib
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session per request for AS2 Server (which currently defaults to tenant 0).
    For the API service, you should use `identity.dependencies.get_tenant_session` instead.
    """
    db_router = getattr(request.app.state, "db_router", None)
    if not db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    # The AS2 server currently hardcodes tenant_id 0 (Host Company) or 1 for legacy compatibility
    # until we implement dynamic AS2 routing.
    # For now, we connect to shard_1.
    shard_url = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"

    async_gen = db_router.get_tenant_session(tenant_id=0, shard_key="shard_1", shard_url=shard_url)

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
