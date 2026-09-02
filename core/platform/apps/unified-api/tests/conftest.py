import asyncio
import contextlib
import hashlib
import os
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
)
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ZITADEL_ISSUER", "http://mock-zitadel")
os.environ.setdefault("ZITADEL_API_URL", "http://mock-zitadel")

import httpx
import pytest
import pytest_asyncio
from database.constants import DatabaseShardStatus
from database.models import Role as OrmRole
from database.models.identity import ApiToken as ApiTokenORM
from database.models.identity import Tenant as TenantORM
from database.provider import get_async_engine
from edi.adapters.outbound.database.models.data_plane import TenantBase
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from seedwork import generate_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp.application.use_cases import api_key_authenticator
from ucp.domain.constants import LifecycleStatus
from ucp_models.infrastructure import DatabaseShard as UcpDatabaseShard
from ucp_models.infrastructure import ShardRegistry as UcpShardRegistry
from ucp_models.subscriptions import App as UcpApp
from ucp_models.subscriptions import AppSubscription as UcpAppSubscription

from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.main import app as _app
from unified_api.main import edi_app


def mock_build_machine_identity(client_id: str, tenant_id: str) -> IdentityContext:
    return IdentityContext(
        subject=f"machine_{client_id}",
        tenant_id=tenant_id,
        organization_id=None,
        authorized_tenants={tenant_id},
        roles=("m2m_api_client", "PlatformAdmin"),
        permissions=(),
        claims={"client_id": client_id, "is_m2m": True},
        capabilities={
            "platform:admin",
            "tenant:admin",
            "tenant_settings:read",
            "tenant_settings:write",
            "users:read",
            "users:write",
            "roles:read",
            "roles:write",
            "api_keys:read",
            "api_keys:write",
            "webhooks:read",
            "webhooks:write",
        },
    )


@pytest.fixture(autouse=True)
def patch_m2m_identity(monkeypatch):
    monkeypatch.setattr(
        api_key_authenticator, "_build_machine_identity", mock_build_machine_identity
    )


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)

    # In integration tests, the EDI bounded context expects its Tenant schema (e.g. edi_messages)
    # to be present on the tenant shard. Because we patch all connections to point to this single
    # global test database, we must ensure the Tenant models are actually created here.

    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_engine):
    """
    Provide an async_sessionmaker bound to a transaction for isolation.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()

    SessionLocal = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )

    mock_provider = Mock()
    mock_provider.session_factory = SessionLocal

    @contextlib.asynccontextmanager
    async def mock_session():
        async with SessionLocal() as session:
            yield session

    mock_provider.session = mock_session
    mock_provider.close = AsyncMock()

    async def mock_global_session(*args, **kwargs):
        async with SessionLocal() as session:
            session.info["session_type"] = "global"
            yield session

    async def mock_tenant_session(*args, **kwargs):
        async with SessionLocal() as session:
            session.info["session_type"] = "tenant"
            yield session

    mock_router = Mock()
    mock_router.get_global_session = mock_global_session
    mock_router.get_tenant_session = mock_tenant_session
    mock_router.close_all = AsyncMock()

    # Patch the session makers across all domains that unified_api touches
    with (
        patch("database.provider.DatabaseProvider.from_url", return_value=mock_provider),
        patch("edi.bootstrap.lifespan.DatabaseRouter", return_value=mock_router),
    ):
        yield SessionLocal

    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def app(db_session_factory):  # noqa: C901
    """
    Returns the real Unified API shell with the patched database sessions.
    """

    class MockSecretStore:
        async def get_secret(self, key: str) -> str | None:
            return None

        async def create_secret(self, key: str, value: str) -> str:
            return f"arn:mock:{key}"

        async def store_private_key(
            self, private_key_pem: bytes, category: str | None = None
        ) -> str:
            return "mock_vault_ref_priv"

        async def store_public_certificate(
            self, tenant_id: str, cert_id: str, public_cert_pem: str
        ) -> str:
            return f"mock_vault_ref_pub_{cert_id}"

        async def store_secret(self, tenant_id: str, secret_id: str, value: str) -> str:
            return f"mock_vault_ref_sec_{secret_id}"

        async def retrieve_secret(self, vault_ref: str) -> bytes:
            return b"mock_secret"

        async def retrieve_private_key(self, vault_ref: str) -> bytes:
            return b"mock_private_key"

        async def retrieve_public_certificate(self, vault_ref: str) -> str:
            return "mock_public_certificate"

        async def list_secrets(self, tenant_id: str) -> list[str]:
            return []

        async def delete_secret(self, vault_ref: str) -> None:
            pass

    async def override_get_secret_store():
        return MockSecretStore()

    _app.dependency_overrides[get_secret_store] = override_get_secret_store
    edi_app.dependency_overrides[get_secret_store] = override_get_secret_store

    async with shell_lifespan(_app):
        yield _app


@pytest_asyncio.fixture(scope="function")
async def client(app):
    """
    Unauthenticated test client.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="function")
async def seeded_api_token(db_session_factory):
    """
    Seeds a valid Tenant and API token into the database and returns the raw secret.
    """
    async with db_session_factory() as session:
        # Seed global roles

        # Seed platform tenant
        platform_tenant = await session.get(TenantORM, PLATFORM_TENANT_ID)
        if not platform_tenant:
            platform_tenant = TenantORM(
                id=PLATFORM_TENANT_ID,
                name="Platform Admin Tenant",
                slug="platform-admin",
                status=LifecycleStatus.ACTIVE,
            )
            session.add(platform_tenant)
            await session.flush()

        admin_role = await session.get(OrmRole, "role_admin")
        if not admin_role:
            admin_role = OrmRole(
                id="role_admin",
                tenant_id=PLATFORM_TENANT_ID,
                name="admin",
                description="Global Administrator",
                capabilities=["*"],
            )
            session.add(admin_role)

        tenant_id = generate_id("iam_ten")
        tenant = await session.get(TenantORM, tenant_id)
        if not tenant:
            tenant = TenantORM(
                id=tenant_id,
                name="Test Auth Tenant",
                slug="test-auth-tenant",
                status=LifecycleStatus.ACTIVE,
                idp_tenant_id="org_test",
            )
            session.add(tenant)
            await session.flush()

        # Seed EDI app and subscription to allow EDI routes to pass the guard

        apps_res = await session.execute(text("SELECT id FROM ucp.apps WHERE slug = 'edi'"))
        existing_app_id = apps_res.scalar() or "app_edi_core"

        existing_app = await session.get(UcpApp, existing_app_id)
        if not existing_app:
            async with session.begin_nested():
                edi_app = UcpApp(
                    id=existing_app_id, slug="edi", name="EDI Gateway", description="EDI"
                )
                session.add(edi_app)
                await session.flush()

        existing_sub = await session.execute(
            text(
                "SELECT tenant_id FROM ucp.app_subscriptions WHERE tenant_id = :tenant_id AND app_id = :app_id"
            ),
            {"tenant_id": tenant_id, "app_id": existing_app_id},
        )
        if not existing_sub.scalar():
            async with session.begin_nested():
                edi_sub = UcpAppSubscription(
                    tenant_id=tenant_id,
                    app_id=existing_app_id,
                    status=LifecycleStatus.ACTIVE,
                    tier="free",
                )
                session.add(edi_sub)
                await session.flush()

        existing_shard = await session.get(UcpDatabaseShard, "edi_shard_1")
        if not existing_shard:
            async with session.begin_nested():
                shard = UcpDatabaseShard(
                    id="edi_shard_1",
                    name="EDI Primary Shard",
                    dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
                    status=DatabaseShardStatus.ACTIVE,
                )
                session.add(shard)
                await session.flush()

        existing_shard_reg = await session.execute(
            text(
                "SELECT tenant_id FROM ucp.shard_registry WHERE tenant_id = :tenant_id AND app_id = :app_id"
            ),
            {"tenant_id": tenant_id, "app_id": existing_app_id},
        )
        if not existing_shard_reg.scalar():
            async with session.begin_nested():
                shard_reg = UcpShardRegistry(
                    tenant_id=tenant_id, app_id=existing_app_id, shard_id="edi_shard_1"
                )
                session.add(shard_reg)
                await session.flush()
        # Create API token
        raw_secret = "test_super_secret"  # noqa: S105
        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

        client_id = "client_test_123"
        token = ApiTokenORM(
            id=generate_id("tok"),
            tenant_id=tenant_id,
            name="Integration Test Token",
            client_id=client_id,
            secret_hash=secret_hash,
            active=True,
        )
        session.add(token)
        await session.commit()

        return {
            "tenant_id": tenant_id,
            "client_id": client_id,
            "raw_secret": raw_secret,
            "header_value": f"sp_api_{client_id}.{raw_secret}",
        }


from identity.domain.identity_context import IdentityContext


@pytest_asyncio.fixture(scope="function")
async def auth_client(app, seeded_api_token):
    """
    Authenticated test client using a valid API token.
    Patches the token verifier to grant the PLATFORM_ADMIN capability
    since API Tokens natively lack that global capability in the DB.
    """
    transport = httpx.ASGITransport(app=app)

    mock_identity = IdentityContext(
        subject="usr_platform_admin_123",
        tenant_id=seeded_api_token["tenant_id"],
        organization_id=None,
        authorized_tenants={seeded_api_token["tenant_id"], "ten_000000000000000000000000"},
        tenant_roles={"ten_000000000000000000000000": ["admin"]},
        roles=("platform_admin",),
        permissions=(),
        claims={"is_m2m": True},
        capabilities={"*"},
    )

    with patch(
        "ucp.application.use_cases.authenticators.api_key_strategy.authenticate_api_key",
        return_value=mock_identity,
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.headers.update({"Authorization": f"Bearer {seeded_api_token['header_value']}"})
            yield c


@pytest_asyncio.fixture(scope="function")
async def simulate_idp_provisioning(db_session_factory):
    """
    Fixture that simulates the identity worker setting idp_user_id on a newly
    created user — using the real PostgresUserRepository and User domain model
    (NOT raw SQL), preserving full hexagonal architecture integrity.

    In production, this is performed asynchronously by the identity worker
    after consuming the `user_created` outbox event and calling the IdP.
    In tests, we invoke the same domain pathway synchronously.

    Usage:
        user_id = res.json()["userId"]
        await simulate_idp_provisioning(user_id)
    """

    async def _provision(user_id: str) -> None:
        async with db_session_factory() as session:
            repo = PostgresUserRepository(session)
            user = await repo.find_by_id(user_id)
            if user is None:
                raise ValueError(
                    f"simulate_idp_provisioning: user '{user_id}' not found. "
                    "Ensure the user was created before calling this fixture."
                )
            # Mirror what the identity worker does: set the IDP user ID on the
            # domain model, then persist via the repository (not raw SQL).
            user.set_idp_user_id(f"mock_idp_{user_id}")
            await repo.save(user)
            await session.commit()

    return _provision
