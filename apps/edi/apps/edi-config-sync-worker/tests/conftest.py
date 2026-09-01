import pytest


@pytest.fixture
def sqs_endpoint() -> str:
    import os

    return os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")


import os
from collections.abc import AsyncGenerator

from database.provider import get_async_engine
from database.router import DatabaseRouterPort
from database.testing import TransactionalTestRouter


@pytest.fixture
async def test_db_router() -> "AsyncGenerator[DatabaseRouterPort, None]":
    global_url = (
        os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
        )
        .replace("postgres://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    shard_url = (
        os.getenv("SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1")
        .replace("postgres://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )

    global_engine = get_async_engine(global_url)
    shard_engine = get_async_engine(shard_url)

    global_conn = await global_engine.connect()
    global_trans = await global_conn.begin()

    shard_conn = await shard_engine.connect()
    shard_trans = await shard_conn.begin()

    test_router = TransactionalTestRouter(
        global_conn=global_conn,
        shard_conn=shard_conn,
        global_url=global_url,
        shard_url=shard_url,
    )

    yield test_router

    await global_trans.rollback()
    await global_conn.close()
    await global_engine.dispose()

    await shard_trans.rollback()
    await shard_conn.close()
    await shard_engine.dispose()
