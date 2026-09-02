import os
from collections.abc import AsyncGenerator

import pytest
from database.provider import get_async_engine
from sqlalchemy import select, text
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
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            factory = async_sessionmaker(
                bind=connection,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                yield session
        finally:
            if transaction.is_active:
                await transaction.rollback()

    await engine.dispose()


@pytest.mark.integration
async def test_ucp_models_persistence_and_relationships(test_session: AsyncSession) -> None:
    # 1. We must insert a Tenant first because ShardRegistry and AppSubscription have FK to identity.tenants

    suffix = os.urandom(12).hex()
    tenant_id = f"iam_ten_{suffix}"
    shard_id = f"ucp_shard_{suffix}"
    outbox_id = f"cp_ucp_ob_{suffix}"

    await test_session.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) "
            "VALUES (:tenant_id, :name, :slug, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"tenant_id": tenant_id, "name": f"Test Tenant {suffix}", "slug": f"test-tenant-{suffix}"},
    )

    # 2. Persist App
    app = App(
        slug=f"test-app-{suffix}",
        name="Test App Name",
        description="A great app",
    )
    test_session.add(app)
    await test_session.flush()
    assert app.id is not None
    assert app.created_at is not None

    # 3. Persist DatabaseShard
    shard = DatabaseShard(
        id=shard_id,
        name=f"ucp_shard_{suffix}",
        dsn="postgres://fake",
    )
    test_session.add(shard)
    await test_session.flush()
    assert shard.created_at is not None

    # 4. Persist ShardRegistry
    registry = ShardRegistry(
        tenant_id=tenant_id,
        app_id=app.id,
        shard_id=shard.id,
    )
    test_session.add(registry)

    # 5. Persist AppSubscription
    sub = AppSubscription(
        tenant_id=tenant_id,
        app_id=app.id,
        tier="enterprise",
    )
    test_session.add(sub)

    # 6. Persist ControlPlaneOutbox
    outbox = ControlPlaneOutbox(
        id=outbox_id,
        tenant_id=tenant_id,
        event_type="test.event",
        idempotency_key=f"iam_key_{suffix}",
        payload={"some": "data"},
        status="PENDING",
    )
    test_session.add(outbox)

    await test_session.commit()

    # Verify we can query them back

    # App
    result = await test_session.execute(select(App).where(App.id == app.id))
    fetched_app = result.scalar_one_or_none()
    assert fetched_app is not None
    assert fetched_app.slug == f"test-app-{suffix}"

    # Sub
    result = await test_session.execute(
        select(AppSubscription).where(AppSubscription.tenant_id == tenant_id)
    )
    fetched_sub = result.scalar_one_or_none()
    assert fetched_sub is not None
    assert fetched_sub.tier == "enterprise"

    # Outbox
    result = await test_session.execute(
        select(ControlPlaneOutbox).where(ControlPlaneOutbox.id == outbox_id)
    )
    fetched_outbox = result.scalar_one_or_none()
    assert fetched_outbox is not None
    assert fetched_outbox.payload == {"some": "data"}

    # Shard
    result = await test_session.execute(select(DatabaseShard).where(DatabaseShard.id == shard_id))
    fetched_shard = result.scalar_one_or_none()
    assert fetched_shard is not None
    assert fetched_shard.name == f"ucp_shard_{suffix}"

    # Shard Registry
    result = await test_session.execute(
        select(ShardRegistry).where(ShardRegistry.tenant_id == tenant_id)
    )
    fetched_registry = result.scalar_one_or_none()
    assert fetched_registry is not None
    assert fetched_registry.shard_id == shard_id
