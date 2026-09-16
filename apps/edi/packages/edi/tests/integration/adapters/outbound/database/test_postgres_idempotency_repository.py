import pytest
from database.models.identity import Tenant
from database.router import DatabaseRouterPort
from pubsub.message import SqsMessagePayload
from sqlalchemy import select, text
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from edi.adapters.outbound.database.data_plane.postgres_idempotency_repository import (
    SqlAlchemyEdiIdempotencyRepository,
)
from edi.adapters.outbound.database.tenant_resolver import TenantResolver

pytestmark = pytest.mark.asyncio


async def test_idempotency_repository_blocks_duplicates(tenant_db_session):
    """
    Integration test for SqlAlchemyEdiIdempotencyRepository.
    Uses a real database connection via the tenant_db_session fixture.
    """

    # Create a fake DatabaseRouter that yields the fixture session
    class FakeDbRouter(DatabaseRouterPort):
        async def get_global_session(self):
            yield tenant_db_session

        async def get_tenant_session(self, tenant_id, shard_key, shard_url):
            yield tenant_db_session

        async def get_shard_session(self, shard_key, shard_url):
            yield tenant_db_session

        async def get_all_shards(self):
            return []

        async def close_all(self):
            pass

    class FakeTenantResolver(TenantResolver):
        def __init__(self):
            pass

        async def resolve(self, tenant_id):
            return "fake_shard", "fake_dsn"

    repo = SqlAlchemyEdiIdempotencyRepository(FakeDbRouter(), FakeTenantResolver())

    tenant_id = "test_tenant"
    idemp_val = "test_idemp_val_123"  # gitleaks:allow

    payload = SqsMessagePayload(
        idempotency_key=idemp_val, tenant_id=tenant_id, event_type="test_event"
    )

    # 1. First time should succeed
    is_new = await repo.check_and_record_idempotency(payload)
    assert is_new is True

    # 2. Second time should fail (duplicate)
    is_new_duplicate = await repo.check_and_record_idempotency(payload)
    assert is_new_duplicate is False

    # 3. Verify it was actually written to the processed_events table
    result = await tenant_db_session.execute(
        text(
            "SELECT * FROM event_idempotency WHERE tenant_id = :tenant_id AND idempotency_key = :key"
        ),
        {"tenant_id": tenant_id, "key": idemp_val},
    )
    rows = result.fetchall()
    assert len(rows) == 1


async def test_idempotency_repository_allows_missing_keys(tenant_db_session):
    class FakeDbRouter(DatabaseRouterPort):
        async def get_global_session(self):
            yield tenant_db_session

        async def get_tenant_session(self, tenant_id, shard_key, shard_url):
            yield tenant_db_session

        async def get_shard_session(self, shard_key, shard_url):
            yield tenant_db_session

        async def get_all_shards(self):
            return []

        async def close_all(self):
            pass

    class FakeTenantResolver(TenantResolver):
        def __init__(self):
            pass

        async def resolve(self, tenant_id):
            return "fake_shard", "fake_dsn"

    repo = SqlAlchemyEdiIdempotencyRepository(FakeDbRouter(), FakeTenantResolver())

    payload = SqsMessagePayload(
        idempotency_key=None, tenant_id="test_tenant", event_type="test_event"
    )

    # Missing idempotency key bypasses the check and returns True
    is_new = await repo.check_and_record_idempotency(payload)
    assert is_new is True


async def test_idempotency_repository_real_router(db_session, tenant_db_session):
    """
    Integration test exercising the real TenantResolver query logic.
    We seed the data in the test transaction and provide a router that yields that transaction.
    """
    tenant_id = "test_real_router_tenant"

    # 1. Seed data required by TenantResolver
    db_session.add(Tenant(id=tenant_id, name="Test Tenant", slug="test-tenant"))

    app = await db_session.scalar(select(App).where(App.slug == "edi"))
    if not app:
        app = App(id="app_edi_1", name="EDI App", slug="edi")
        db_session.add(app)

    shard = await db_session.scalar(
        select(DatabaseShard).where(DatabaseShard.name == "edi_shard_1")
    )
    if not shard:
        shard = DatabaseShard(id="shard_1", name="edi_shard_1", dsn="postgresql+asyncpg://dummy")
        db_session.add(shard)

    await db_session.flush()
    db_session.add(ShardRegistry(tenant_id=tenant_id, app_id=app.id, shard_id=shard.id))
    await db_session.flush()

    # 2. Fake router that yields the test transactions
    class TxRouter(DatabaseRouterPort):
        async def get_global_session(self):
            yield db_session

        async def get_tenant_session(self, tenant_id, shard_key, shard_url):
            yield tenant_db_session

        async def get_shard_session(self, shard_key, shard_url):
            yield tenant_db_session

        async def get_all_shards(self):
            return []

        async def close_all(self):
            pass

    router = TxRouter()
    resolver = TenantResolver(router)
    repo = SqlAlchemyEdiIdempotencyRepository(router, resolver)

    payload = SqsMessagePayload(
        idempotency_key="real_router_key_1", tenant_id=tenant_id, event_type="test_event"
    )

    is_new = await repo.check_and_record_idempotency(payload)
    assert is_new is True

    is_new_duplicate = await repo.check_and_record_idempotency(payload)
    assert is_new_duplicate is False
