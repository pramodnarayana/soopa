import asyncio
import contextlib
import hashlib
import os
import secrets
import tempfile

import database.provider
import edi.bootstrap.lifespan
import httpx
import ip.application.domains.energy.models as _ip_energy_models
import ip.application.domains.tms.models as _ip_tms_models
import ip.engine.adapters.outbound.database.models.control_plane as _ip_cp_models
import ip.engine.adapters.outbound.database.models.data_plane as _ip_dp_models
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
from ip.engine.adapters.outbound.database.models.base import IpGlobalBase, IpTenantBase
from orchestration.adapters.outbound.database.models import WorkflowBase
from secret_store import AwsSecretsManagerAdapter

_IP_MODEL_MODULES = (
    _ip_energy_models,
    _ip_tms_models,
    _ip_cp_models,
    _ip_dp_models,
)
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp.application.use_cases import api_key_authenticator
from ucp.domain.constants import LifecycleStatus
from ucp_models.sharding import DatabaseShard as UcpDatabaseShard
from ucp_models.sharding import ShardRegistry as UcpShardRegistry
from ucp_models.subscriptions import App as UcpApp
from ucp_models.subscriptions import AppSubscription as UcpAppSubscription

from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.main import app as _app
from unified_api.main import edi_app


def fake_build_machine_identity(client_id: str, tenant_id: str) -> IdentityContext:
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
        api_key_authenticator, "_build_machine_identity", fake_build_machine_identity
    )


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


_IP_TENANT_TABLES_SYNCED = False


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    global _IP_TENANT_TABLES_SYNCED
    db_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(db_url)

    # In integration tests, ensure schemas and tables exist on the test database
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ip;"))
        if not _IP_TENANT_TABLES_SYNCED:
            await conn.run_sync(IpTenantBase.metadata.drop_all)
            _IP_TENANT_TABLES_SYNCED = True
        await conn.run_sync(TenantBase.metadata.create_all)
        await conn.run_sync(IpGlobalBase.metadata.create_all)
        await conn.run_sync(IpTenantBase.metadata.create_all)
        await conn.run_sync(WorkflowBase.metadata.create_all)

    yield engine
    await engine.dispose()


class FakeDatabaseProvider:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @contextlib.asynccontextmanager
    async def session(self):
        async with self.session_factory() as session:
            yield session

    async def close(self):
        pass


class FakeDatabaseRouter:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_global_session(self, *args, **kwargs):
        async with self.session_factory() as session:
            session.info["session_type"] = "global"
            yield session

    async def get_tenant_session(self, *args, **kwargs):
        async with self.session_factory() as session:
            session.info["session_type"] = "tenant"
            yield session

    async def close_all(self):
        pass


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_engine, monkeypatch):
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

    fake_provider = FakeDatabaseProvider(SessionLocal)
    fake_router = FakeDatabaseRouter(SessionLocal)

    monkeypatch.setattr(
        database.provider.DatabaseProvider, "from_url", classmethod(lambda cls, url: fake_provider)
    )

    monkeypatch.setattr(
        edi.bootstrap.lifespan, "DatabaseRouter", lambda *args, **kwargs: fake_router
    )
    monkeypatch.setattr(
        "unified_api.bootstrap.lifespan.DatabaseRouter", lambda *args, **kwargs: fake_router
    )

    yield SessionLocal

    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def app(db_session_factory):
    """
    Returns the real Unified API shell with the patched database sessions.
    """

    temp_secrets_dir = tempfile.mkdtemp()

    async def override_get_secret_store():
        return AwsSecretsManagerAdapter(secrets_mount_path=temp_secrets_dir)

    _app.dependency_overrides[get_secret_store] = override_get_secret_store
    if edi_app is not None:
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


async def _seed_app_and_shard(
    session: AsyncSession,
    *,
    tenant_id: str,
    app_slug: str,
    default_app_id: str,
    app_name: str,
    app_description: str,
    tier: str,
    shard_id: str,
    shard_name: str,
) -> None:
    apps_res = await session.execute(
        text("SELECT id FROM ucp.apps WHERE slug = :slug"),
        {"slug": app_slug},
    )
    existing_app_id = str(apps_res.scalar() or default_app_id)

    existing_app = await session.get(UcpApp, existing_app_id)
    if not existing_app:
        async with session.begin_nested():
            session.add(
                UcpApp(
                    id=existing_app_id,
                    slug=app_slug,
                    name=app_name,
                    description=app_description,
                )
            )
            await session.flush()

    existing_sub = await session.execute(
        text(
            "SELECT tenant_id FROM ucp.app_subscriptions WHERE tenant_id = :tenant_id AND app_id = :app_id"
        ),
        {"tenant_id": tenant_id, "app_id": existing_app_id},
    )
    if not existing_sub.scalar():
        async with session.begin_nested():
            session.add(
                UcpAppSubscription(
                    tenant_id=tenant_id,
                    app_id=existing_app_id,
                    status=LifecycleStatus.ACTIVE,
                    tier=tier,
                )
            )
            await session.flush()

    existing_shard = await session.get(UcpDatabaseShard, shard_id)
    if not existing_shard:
        async with session.begin_nested():
            session.add(
                UcpDatabaseShard(
                    id=shard_id,
                    name=shard_name,
                    dsn=os.environ["TEST_SHARD_DB_URL"],
                    status=DatabaseShardStatus.ACTIVE,
                )
            )
            await session.flush()

    existing_shard_reg = await session.execute(
        text(
            "SELECT tenant_id FROM ucp.shard_registry WHERE tenant_id = :tenant_id AND app_id = :app_id"
        ),
        {"tenant_id": tenant_id, "app_id": existing_app_id},
    )
    if not existing_shard_reg.scalar():
        async with session.begin_nested():
            session.add(
                UcpShardRegistry(
                    tenant_id=tenant_id,
                    app_id=existing_app_id,
                    shard_id=shard_id,
                )
            )
            await session.flush()


@pytest_asyncio.fixture(scope="function")
async def seeded_api_token(db_session_factory):
    """
    Seeds a valid Tenant and API token into the database and returns the raw secret.
    """
    async with db_session_factory() as session:
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

        tenant_id = generate_id(DomainIdPrefix.TENANT.value)
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

        await _seed_app_and_shard(
            session,
            tenant_id=tenant_id,
            app_slug="edi",
            default_app_id="app_edi_core",
            app_name="EDI Gateway",
            app_description="EDI",
            tier="free",
            shard_id="edi_shard_1",
            shard_name="EDI Primary Shard",
        )
        await _seed_app_and_shard(
            session,
            tenant_id=tenant_id,
            app_slug="ip",
            default_app_id="app_ip_core",
            app_name="Integration Platform",
            app_description="Enterprise Integration Platform",
            tier="enterprise",
            shard_id="ip_shard_1",
            shard_name="IP Primary Shard",
        )

        # Create API token
        raw_secret = secrets.token_urlsafe(32)
        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

        client_id = "client_test_123"
        token = ApiTokenORM(
            id=generate_id(DomainIdPrefix.TOKEN.value),
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
async def auth_client(app, seeded_api_token, monkeypatch):
    """
    Authenticated test client using a valid API token.
    Patches the token verifier to grant the PLATFORM_ADMIN capability
    since API Tokens natively lack that global capability in the DB.
    """
    transport = httpx.ASGITransport(app=app)

    fake_identity = IdentityContext(
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

    async def fake_authenticate_api_key(*args, **kwargs):
        return fake_identity

    monkeypatch.setattr(
        "ucp.application.use_cases.authenticators.api_key_strategy.authenticate_api_key",
        fake_authenticate_api_key,
    )

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
            user.set_idp_user_id(f"fake_idp_{user_id}")
            await repo.save(user)
            await session.commit()

    return _provision
