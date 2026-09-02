import contextlib
import os
from collections.abc import AsyncGenerator

import pytest
from database.router import DatabaseRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# We use the local test databases spun up by docker-compose, but allow overrides.
# Since Node.js and Python share the DATABASE_URL environment variable,
# we safely mutate the dialect to asyncpg for Python using SQLAlchemy's URL parser.
@pytest.fixture
async def router() -> AsyncGenerator[DatabaseRouter, None]:
    # Setup
    global_db_url = os.environ["DATABASE_URL"]
    db_router = DatabaseRouter(global_db_url, pool_size=2, max_overflow=2)
    yield db_router
    # Teardown
    await db_router.close_all()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.integration
async def test_global_session_connection(router: DatabaseRouter) -> None:
    """
    Test that the DatabaseRouter can successfully yield a session
    connected to the global database.
    """
    async_gen = router.get_global_session()
    session: AsyncSession = await async_gen.__anext__()
    try:
        # Simple query to verify connection
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.integration
async def test_tenant_session_rls_enforcement(router: DatabaseRouter) -> None:
    """
    Test that yielding a tenant session dynamically connects to the correct shard
    and fundamentally applies the PostgreSQL Row-Level Security parameter.
    """
    tenant_id = "999"

    shards = await router.get_all_shards()
    assert shards, "No shards found in global database!"
    shard_id, shard_url = shards[0]

    async_gen = router.get_tenant_session(
        tenant_id=tenant_id, shard_key=shard_id, shard_url=shard_url
    )

    session: AsyncSession = await async_gen.__anext__()
    try:
        # Verify the RLS setting was successfully applied in the current transaction
        result = await session.execute(text("SELECT current_setting('app.current_tenant')"))
        applied_tenant_id = result.scalar()

        assert applied_tenant_id == tenant_id, "RLS current_tenant was not set correctly!"
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
