import os
from typing import Any

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ.setdefault("ZITADEL_API_TOKEN", "mock_token")
os.environ.setdefault("ZITADEL_UCP_PROJECT_ID", "mock_project_id")
os.environ.setdefault("ZITADEL_PLATFORM_ORG_ID", "mock_org_id")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://mock:mock@localhost:5432/mock")
import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from platform_orm.models.core import GlobalRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from ucp_api.adapters.inbound.http.guards import platform_auth_guard, tenant_auth_guard
from ucp_api.main import (  # type: ignore
    app,
    get_db_session,
    get_org_provider,
    get_project_provider,
    get_user_provider,
)

# ---------------------------------------------------------------------------
# Shared mock identity \u2014 a Platform Admin used across all integration tests.
# We inject this directly so we never need a real Zitadel instance during tests.
# ---------------------------------------------------------------------------
MOCK_PLATFORM_ADMIN = IdentityContext(
    subject="test-user-sub",
    tenant_id=PLATFORM_TENANT_ID,
    authorized_tenants={PLATFORM_TENANT_ID},
    claims={},
)


async def _mock_platform_admin_guard() -> IdentityContext:
    return MOCK_PLATFORM_ADMIN


async def _mock_tenant_member_guard() -> IdentityContext:
    return MOCK_PLATFORM_ADMIN


@pytest.fixture(scope="session")
def event_loop() -> "Any":
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> "Any":
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_container) -> "Any":  # type: ignore
    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ucp"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS edi"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS scheduling"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS notifications"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS observability"))

        # Ensure models are imported

        await conn.run_sync(GlobalRegistry.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> "Any":  # type: ignore
    SessionLocal = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    session = SessionLocal()
    yield session
    await session.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_session) -> "Any":  # type: ignore
    async def override_get_db_session() -> "Any":
        yield db_session

    def override_get_org_provider() -> "Any":
        mock = AsyncMock()
        mock.create_organization.return_value = ("mock-org-123", True)
        mock.delete_organization.return_value = None
        return mock

    def override_get_project_provider() -> "Any":
        mock = AsyncMock()
        mock.get_roles.return_value = []
        return mock

    def override_get_user_provider() -> "Any":
        mock = AsyncMock()
        mock.create_user.return_value = "mock-user-123"
        mock.assign_tenant_role.return_value = None
        mock.update_tenant_role.return_value = None
        mock.update_user_profile.return_value = None
        mock.delete_user.return_value = None
        return mock

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_org_provider] = override_get_org_provider
    app.dependency_overrides[get_project_provider] = override_get_project_provider
    app.dependency_overrides[get_user_provider] = override_get_user_provider
    # Override the auth guard inner dependencies to bypass real JWT verification.
    # This correctly isolates the "boundary" (JWT token parsing) from the business logic.
    app.dependency_overrides[platform_auth_guard.require_platform_admin] = (
        _mock_platform_admin_guard
    )
    app.dependency_overrides[tenant_auth_guard.require_tenant_member] = _mock_tenant_member_guard

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides = old_overrides
