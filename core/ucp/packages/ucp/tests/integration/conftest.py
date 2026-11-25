import asyncio
import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from unified_api.adapters.inbound.http.guards import platform_auth_guard, tenant_auth_guard
from unified_api.adapters.inbound.http.guards.require_capability_guard import RequireCapability
from unified_api.main import app

from ucp.bootstrap.dependencies import (
    get_db_session,
)

pytestmark = pytest.mark.integration

os.environ.setdefault(
    "IDENTITY_MACHINE_KEY",
    '{"keyId":"fake-key","key":"fake-private-key","userId":"fake-user"}',
)

# ---------------------------------------------------------------------------
# Shared fake identity — a Platform Admin used across all integration tests.
# We inject this directly so we never need a real Zitadel instance during tests.
# ---------------------------------------------------------------------------
FAKE_PLATFORM_ADMIN = IdentityContext(
    subject="usr_fake_admin",
    tenant_id=PLATFORM_TENANT_ID,
    authorized_tenants={PLATFORM_TENANT_ID},
    tenant_roles={PLATFORM_TENANT_ID: ["admin"]},
    claims={},
)


async def _fake_platform_admin_guard(request: Request) -> IdentityContext:
    request.state.identity = FAKE_PLATFORM_ADMIN
    request.state.ucp_tenant_id = PLATFORM_TENANT_ID
    return FAKE_PLATFORM_ADMIN


async def _fake_tenant_member_guard(request: Request) -> IdentityContext:
    request.state.identity = FAKE_PLATFORM_ADMIN
    # Try to grab tenant_id from path params if it exists, otherwise use platform
    tenant_id = request.path_params.get("tenant_id", PLATFORM_TENANT_ID)
    request.state.ucp_tenant_id = tenant_id
    return FAKE_PLATFORM_ADMIN


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    db_url = os.environ["DATABASE_URL"]
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    connection = await db_engine.connect()
    transaction = await connection.begin()

    SessionLocal = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()
    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def client(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_session] = override_get_db_session
    # Override the auth guard inner dependencies to bypass real JWT verification.
    # This correctly isolates the "boundary" (JWT token parsing) from the business logic.
    app.dependency_overrides[platform_auth_guard.require_platform_admin] = (
        _fake_platform_admin_guard
    )
    app.dependency_overrides[tenant_auth_guard.require_tenant_member] = _fake_tenant_member_guard

    # Also patch RequireCapability since it reads directly from request.state.identity

    def fake_require_capability(self, request: Request) -> IdentityContext:
        request.state.identity = FAKE_PLATFORM_ADMIN
        return FAKE_PLATFORM_ADMIN

    monkeypatch.setattr(RequireCapability, "__call__", fake_require_capability)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides = old_overrides
