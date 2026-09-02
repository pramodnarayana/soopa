import os

from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from unified_api.adapters.inbound.http.dependencies.edi.auth import (
    get_current_tenant_id,
    get_current_user_profile,
    get_platform_user_profile,
    require_platform_admin,
)
from unified_api.adapters.inbound.http.dependencies.edi.database import (
    get_data_plane_uow,
    get_global_session,
    get_tenant_session,
)
from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store

from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWorkPort,
)
from edi.module import create_edi_app

os.environ["DB_ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
)
import asyncio
from typing import Any

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from sqlalchemy import text


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create an async SQLAlchemy engine pointing to the test database."""
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine):
    """Provide a connection with an active transaction that rolls back after each test."""
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_engine():
    """Create an async SQLAlchemy engine pointing to the tenant shard test database."""
    db_url = os.getenv(
        "SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_connection(tenant_db_engine):
    """Provide a connection with an active transaction that rolls back after each test."""
    connection = await tenant_db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_connection):
    """
    Provide an AsyncSession that rolls back after each test.
    This guarantees test isolation.
    """
    SessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )

    session = SessionLocal()
    yield session
    await session.close()


@pytest_asyncio.fixture(scope="function")
async def override_get_global_session(db_connection):

    SessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        info={"session_type": "global"},
        join_transaction_mode="create_savepoint",
    )

    async def _override():
        async with SessionLocal() as session:
            yield session

    return _override


@pytest_asyncio.fixture(scope="function")
async def override_get_tenant_session(tenant_db_connection):

    SessionLocal = async_sessionmaker(
        bind=tenant_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        info={"session_type": "tenant"},
        join_transaction_mode="create_savepoint",
    )

    async def _override(tenant_id: str = Depends(get_current_tenant_id)):
        async with SessionLocal() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id}';"))
            yield session

    return _override


class FakeVault:
    async def get_secret(self, vault_ref: str) -> str:
        return "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        val = await self.get_secret(vault_ref)
        return val.encode("utf-8")

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def store_private_key(self, private_key_pem: bytes, category: Any = None) -> str:
        return "vault_ref_123"

    async def delete_secret(self, vault_ref: str) -> None:
        pass


@pytest.fixture(scope="function")
def override_get_secret_store():
    return FakeVault()


@pytest_asyncio.fixture(scope="function")
async def client(
    override_get_global_session, override_get_tenant_session, override_get_secret_store
):

    app = create_edi_app()

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_global_session] = override_get_global_session
    app.dependency_overrides[get_tenant_session] = override_get_tenant_session
    app.dependency_overrides[get_secret_store] = lambda: override_get_secret_store
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "sub": "test-user",
        "tenant_id": "1",
        "permissions": ["*"],
    }
    app.dependency_overrides[get_platform_user_profile] = lambda: {
        "sub": "test-user",
        "tenant_id": PLATFORM_TENANT_ID,
        "permissions": ["platform:admin"],
    }

    async def _uow():
        gs_gen = override_get_global_session()
        ts_gen = override_get_tenant_session("1")
        await gs_gen.__anext__()
        ts = await ts_gen.__anext__()
        try:
            yield DataPlaneUnitOfWorkPort(tenant_session=ts)
        finally:
            await gs_gen.aclose()
            await ts_gen.aclose()

    app.dependency_overrides[get_data_plane_uow] = _uow

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides = old_overrides


@pytest_asyncio.fixture(scope="function")
async def platform_client(
    override_get_global_session, override_get_tenant_session, override_get_secret_store
):

    app = create_edi_app()

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_global_session] = override_get_global_session
    app.dependency_overrides[get_tenant_session] = override_get_tenant_session
    app.dependency_overrides[get_secret_store] = lambda: override_get_secret_store
    app.dependency_overrides[get_current_tenant_id] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID

    app.dependency_overrides[get_platform_user_profile] = lambda: {
        "sub": "admin-user",
        "tenant_id": PLATFORM_TENANT_ID,
        "permissions": ["platform:admin"],
    }
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "sub": "admin-user",
        "tenant_id": PLATFORM_TENANT_ID,
        "permissions": ["*"],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides = old_overrides
