from sqlalchemy import text

"""
Enterprise Database Testing Utilities.

Provides a TransactionalTestRouter that implements the DatabaseRouterPort.
This allows tests to run inside a nested Savepoint for fast rollbacks without
polluting the production router with test logic or violating the Open/Closed Principle.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession


class TransactionalTestRouter(DatabaseRouterPort):
    """
    Test implementation of the Database Router.
    Uses pre-bound connections injected via Pytest fixtures, wrapped in Savepoints.
    """

    def __init__(
        self,
        global_conn: AsyncConnection,
        shard_conn: AsyncConnection,
        global_url: str,
        shard_url: str,
    ):
        self.global_conn = global_conn
        self.shard_conn = shard_conn
        self.global_url = global_url
        self.shard_url = shard_url
        self.global_db_lock = asyncio.Lock()
        self.shard_db_lock = asyncio.Lock()

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        async with self.global_db_lock:
            factory = async_sessionmaker(
                bind=self.global_conn,
                expire_on_commit=False,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                session.info["session_type"] = "global"
                yield cast(GlobalSession, session)

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        async with self.shard_db_lock:
            factory = async_sessionmaker(
                bind=self.shard_conn,
                expire_on_commit=False,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
            )

            try:
                async with factory() as session:
                    await session.execute(
                        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                        {"tenant_id": tenant_id},
                    )
                    session.info["session_type"] = "tenant"
                    yield cast(TenantSession, session)
            finally:
                await self.shard_conn.execute(
                    text("SELECT set_config('app.current_tenant', '', true)")
                )

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        async with self.shard_db_lock:
            factory = async_sessionmaker(
                bind=self.shard_conn,
                expire_on_commit=False,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                session.info["session_type"] = "tenant"
                yield cast(TenantSession, session)

    async def get_all_shards(self) -> list[tuple[str, str]]:
        return [("ucp_shard_1", self.shard_url)]

    async def close_all(self) -> None:
        pass


async def get_test_shard_url_async(global_db_url: str) -> str:
    """
    Dynamically fetches the first active testing shard URL using the production DatabaseRouter.
    """
    from database.router import DatabaseRouter

    router = DatabaseRouter(global_db_url=global_db_url)
    shards = await router.get_all_shards()
    await router.close_all()
    if not shards:
        raise ValueError("No test shards found in the Control Plane.")
    return shards[0][1]


def get_test_shard_url_sync(global_db_url: str) -> str:
    """
    Synchronous wrapper for get_test_shard_url_async.
    Use this in module-level declarations and non-async test scripts.
    """
    return asyncio.run(get_test_shard_url_async(global_db_url))
