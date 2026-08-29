import os
from collections.abc import AsyncGenerator

import pytest
from database.provider import get_async_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App, AppSubscription

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_session() -> "AsyncGenerator[AsyncSession, None]":
    base_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    engine = get_async_engine(base_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture(autouse=True)
async def clear_ucp_tables(test_session: AsyncSession) -> None:
    from sqlalchemy import text

    # Clean up tables we test against
    await test_session.execute(text("TRUNCATE TABLE ucp.outbox RESTART IDENTITY CASCADE;"))
    await test_session.execute(text("TRUNCATE TABLE ucp.database_shards RESTART IDENTITY CASCADE;"))
    await test_session.execute(text("TRUNCATE TABLE ucp.apps RESTART IDENTITY CASCADE;"))
    await test_session.execute(text("TRUNCATE TABLE identity.tenants RESTART IDENTITY CASCADE;"))
    await test_session.commit()


@pytest.mark.integration
async def test_ucp_models_persistence_and_relationships(test_session: AsyncSession) -> None:
    # 1. We must insert a Tenant first because ShardRegistry and AppSubscription have FK to identity.tenants
    from sqlalchemy import text

    await test_session.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) VALUES ('tenant-1', 'Test Tenant', 'test-tenant', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )

    # 2. Persist App
    app = App(
        slug="test-app-slug",
        name="Test App Name",
        description="A great app",
    )
    test_session.add(app)
    await test_session.flush()
    assert app.id is not None
    assert app.created_at is not None

    # 3. Persist DatabaseShard
    shard = DatabaseShard(
        id="shard-1-id",
        name="shard_1_name",
        dsn="postgres://fake",
    )
    test_session.add(shard)
    await test_session.flush()
    assert shard.created_at is not None

    # 4. Persist ShardRegistry
    registry = ShardRegistry(
        tenant_id="tenant-1",
        app_id=app.id,
        shard_id=shard.id,
    )
    test_session.add(registry)

    # 5. Persist AppSubscription
    sub = AppSubscription(
        tenant_id="tenant-1",
        app_id=app.id,
        tier="enterprise",
    )
    test_session.add(sub)

    # 6. Persist ControlPlaneOutbox
    outbox = ControlPlaneOutbox(
        id="cp_ucp_ob_999",
        tenant_id="tenant-1",
        event_type="test.event",
        idempotency_key="key-1",
        payload={"some": "data"},
        status="PENDING",
    )
    test_session.add(outbox)

    await test_session.commit()

    # Verify we can query them back
    from sqlalchemy import select

    # App
    result = await test_session.execute(select(App).where(App.id == app.id))
    fetched_app = result.scalar_one_or_none()
    assert fetched_app is not None
    assert fetched_app.slug == "test-app-slug"

    # Sub
    result = await test_session.execute(
        select(AppSubscription).where(AppSubscription.tenant_id == "tenant-1")
    )
    fetched_sub = result.scalar_one_or_none()
    assert fetched_sub is not None
    assert fetched_sub.tier == "enterprise"

    # Outbox
    result = await test_session.execute(
        select(ControlPlaneOutbox).where(ControlPlaneOutbox.id == "cp_ucp_ob_999")
    )
    fetched_outbox = result.scalar_one_or_none()
    assert fetched_outbox is not None
    assert fetched_outbox.payload == {"some": "data"}

    # Shard
    result = await test_session.execute(
        select(DatabaseShard).where(DatabaseShard.id == "shard-1-id")
    )
    fetched_shard = result.scalar_one_or_none()
    assert fetched_shard is not None
    assert fetched_shard.name == "shard_1_name"

    # Shard Registry
    result = await test_session.execute(
        select(ShardRegistry).where(ShardRegistry.tenant_id == "tenant-1")
    )
    fetched_registry = result.scalar_one_or_none()
    assert fetched_registry is not None
    assert fetched_registry.shard_id == "shard-1-id"
