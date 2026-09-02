import os
from collections.abc import AsyncGenerator

import pytest
from database.provider import get_async_engine
from database.router import DatabaseRouterPort
from database.testing import TransactionalTestRouter, get_test_shard_url_async


@pytest.fixture
async def db_router() -> "AsyncGenerator[DatabaseRouterPort, None]":
    global_url = os.environ["DATABASE_URL"]

    shard_url = await get_test_shard_url_async(global_url)

    global_engine = get_async_engine(global_url)
    shard_engine = get_async_engine(shard_url)

    global_conn = None
    shard_conn = None
    global_trans = None
    shard_trans = None
    try:
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
    finally:
        if global_trans is not None:
            await global_trans.rollback()
        if global_conn is not None:
            await global_conn.close()
        await global_engine.dispose()

        if shard_trans is not None:
            await shard_trans.rollback()
        if shard_conn is not None:
            await shard_conn.close()
        await shard_engine.dispose()
