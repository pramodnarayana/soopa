import os

from identity.domain.identity_context import PLATFORM_TENANT_ID

os.environ["DB_ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://mock:mock@localhost:5432/mock")
import asyncio

import pytest
import pytest_asyncio
from database.models.data_plane import TenantBase

# Assuming Alembic is used for migrations. We can run it programmatically.
# Or we can just use BaseModel.metadata.create_all(bind=engine) for tests.
from platform_orm.models.core import GlobalRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container():
    """Spin up a real Postgres database for the test session."""
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_container):
    """Create an async SQLAlchemy engine pointing to the testcontainer."""
    # testcontainers gives synchronous URL. We replace driver for asyncpg.
    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(db_url, echo=False)

    # Initialize the schema
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS edi"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ucp"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS scheduling"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS notifications"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS observability"))

        # Ensure all models are imported so they are registered with GlobalRegistry

        await conn.run_sync(GlobalRegistry.metadata.drop_all)
        await conn.run_sync(TenantBase.metadata.drop_all)
        await conn.run_sync(GlobalRegistry.metadata.create_all)
        await conn.run_sync(TenantBase.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """
    Provide an AsyncSession that rolls back after each test.
    This guarantees test isolation.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()

    SessionLocal = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)

    session = SessionLocal()
    yield session
    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def override_get_global_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    SessionLocal = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession, info={"session_type": "global"}
    )

    async def _override():
        async with SessionLocal() as session:
            yield session

    return _override


@pytest_asyncio.fixture(scope="function")
async def override_get_tenant_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    SessionLocal = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession, info={"session_type": "tenant"}
    )
    from fastapi import Depends

    from api.dependencies.auth import get_current_tenant_id

    async def _override(tenant_id: str = Depends(get_current_tenant_id)):
        async with SessionLocal() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id}';"))
            yield session

    return _override


class FakeVault:
    def retrieve_secret(self, vault_ref: str) -> bytes:
        return b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"

    def retrieve_private_key(self, vault_ref: str) -> bytes:
        return self.retrieve_secret(vault_ref)

    def store_private_key(self, private_key_pem: bytes, alias_prefix: str = "as2_key") -> str:
        return "fake_ref"

    def delete_secret(self, vault_ref: str) -> None:
        pass


@pytest.fixture(scope="function")
def override_get_vault():
    return FakeVault()


@pytest_asyncio.fixture(scope="function")
async def client(override_get_global_session, override_get_tenant_session, override_get_vault):
    from httpx import ASGITransport, AsyncClient

    from api.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
    from api.auth.api_key import get_tenant_id_from_api_key
    from api.dependencies.auth import (
        get_current_tenant_id,
        get_current_user_profile,
        get_platform_user_profile,
        require_platform_admin,
    )
    from api.dependencies.database import (
        get_data_plane_uow,
        get_global_session,
        get_m2m_data_plane_uow,
        get_tenant_session,
    )
    from api.dependencies.services import get_vault
    from api.main import app

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_global_session] = override_get_global_session
    app.dependency_overrides[get_tenant_session] = override_get_tenant_session
    app.dependency_overrides[get_vault] = lambda: override_get_vault
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    app.dependency_overrides[get_tenant_id_from_api_key] = lambda: "1"
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

    async def _m2m_uow():
        gs_gen = override_get_global_session()
        ts_gen = override_get_tenant_session("1")
        await gs_gen.__anext__()
        ts = await ts_gen.__anext__()
        try:
            yield DataPlaneUnitOfWork(tenant_session=ts)
        finally:
            await gs_gen.aclose()
            await ts_gen.aclose()

    app.dependency_overrides[get_m2m_data_plane_uow] = _m2m_uow
    app.dependency_overrides[get_data_plane_uow] = _m2m_uow

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides = old_overrides


@pytest_asyncio.fixture(scope="function")
async def platform_client(
    override_get_global_session, override_get_tenant_session, override_get_vault
):
    from httpx import ASGITransport, AsyncClient

    from api.dependencies.auth import (
        get_current_tenant_id,
        get_current_user_profile,
        require_platform_admin,
    )
    from api.dependencies.database import (
        get_global_session,
        get_tenant_session,
    )
    from api.dependencies.services import get_vault
    from api.main import app

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_global_session] = override_get_global_session
    app.dependency_overrides[get_tenant_session] = override_get_tenant_session
    app.dependency_overrides[get_vault] = lambda: override_get_vault
    app.dependency_overrides[get_current_tenant_id] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID
    from api.dependencies.auth import get_platform_user_profile

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
