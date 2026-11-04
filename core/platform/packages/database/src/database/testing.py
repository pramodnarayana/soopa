"""
Enterprise Database Testing Utilities.

Provides a TransactionalTestRouter that implements the DatabaseRouterPort and
fail-closed DSN guards ensuring tests never connect to live development databases.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from database.router import DatabaseRouter, DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from database.utils import DEFAULT_TEST_DB_SUFFIX


def assert_test_database_url(url: str) -> str:
    """Fail-closed guard ensuring test suites connect exclusively to isolated test DBs.

    Allows SQLite test URLs and PostgreSQL databases named ``test`` or ending with
    ``_test`` (for example, ``global_db_test``, ``edi_shard_test``). Raises
    ``RuntimeError`` immediately if pointed at a live development database.
    """
    if not url or not url.strip():
        raise RuntimeError("Refusing to run tests against non-test database: empty DSN provided.")

    url_obj = make_url(url)
    if url_obj.drivername.startswith("sqlite"):
        return url

    db_name = (url_obj.database or "").strip("/")
    if not db_name or (db_name != "test" and not db_name.endswith(DEFAULT_TEST_DB_SUFFIX)):
        raise RuntimeError(
            f"Refusing to run tests against non-test database '{db_name or '<empty>'}'. "
            f"Expected a '*{DEFAULT_TEST_DB_SUFFIX}' database "
            "(run via 'pnpm test:integration' or 'infra/local/scripts/run_in_test_env.py')."
        )

    return url


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
        assert_test_database_url(global_url)
        assert_test_database_url(shard_url)
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

    @asynccontextmanager
    async def global_session_scope(self) -> AsyncIterator[GlobalSession]:
        async for session in self.get_global_session():
            yield session

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
                        text("SELECT set_config('platform.current_tenant_id', :tenant_id, true)"),
                        {"tenant_id": tenant_id},
                    )
                    session.info["session_type"] = "tenant"
                    yield cast(TenantSession, session)
            finally:
                await self.shard_conn.execute(
                    text("SELECT set_config('platform.current_tenant_id', '', true)")
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

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        if app_slug == "edi" or "5433" in self.shard_url:
            return [("edi_shard_1", self.shard_url)]
        return [("ucp_shard_1", self.shard_url)]

    async def close_all(self) -> None:
        pass


async def get_test_shard_url_async(global_db_url: str, app_slug: str | None = None) -> str:
    """
    Dynamically fetches the first active testing shard URL using the production DatabaseRouter.

    Reads shard_overrides from the centralized PlatformDatabaseSettings so that
    environment-injected overrides (e.g. SHARD_OVERRIDES__EDI_SHARD_1=localhost:5433)
    are honoured. Without this, the router would return the raw Docker hostname
    stored in the DB registry, which is unresolvable on the host machine.
    """
    db_settings = PlatformDatabaseSettings()
    router = DatabaseRouter(
        global_db_url=global_db_url,
        shard_overrides=db_settings.shard_overrides,
    )
    shards = await router.get_all_shards(app_slug=app_slug)
    await router.close_all()
    if not shards:
        raise ValueError("No test shards found in the Control Plane.")
    for shard_key, shard_url in shards:
        if shard_key.lower() in db_settings.shard_overrides:
            return shard_url
    return shards[0][1]


def get_test_shard_url_sync(global_db_url: str, app_slug: str | None = None) -> str:
    """
    Synchronous wrapper for get_test_shard_url_async.
    Use this in module-level declarations and non-async test scripts.
    """
    return asyncio.run(get_test_shard_url_async(global_db_url, app_slug=app_slug))
