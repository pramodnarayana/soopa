from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from database.models.identity import Tenant
from database.models.sharding import (
    DatabaseShard,
    ShardRegistry,
    VirtualBucketAssignment,
)
from database.models.subscriptions import App
from database.provider import get_async_engine
from database.testing import TransactionalTestRouter, assert_test_database_url
from sqlalchemy.exc import IntegrityError

from sharding.domain.constants import (
    DatabaseShardStatus,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from sharding.provider import ShardingProvider

pytestmark = pytest.mark.integration


@pytest.fixture
async def isolated_test_router() -> AsyncGenerator[TransactionalTestRouter, None]:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        try:
            yield TransactionalTestRouter(
                global_conn=conn,
                shard_conn=conn,
                global_url=db_url,
                shard_url=db_url,
            )
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


@pytest.mark.integration
async def test_sqlalchemy_shard_topology_repository_and_resolver_end_to_end(
    isolated_test_router: TransactionalTestRouter,
) -> None:
    suffix = os.urandom(12).hex()
    app_slug = f"cellular-app-{suffix}"
    app = App(
        id=f"{App.ID_PREFIX}_{suffix}",
        slug=app_slug,
        name="Cellular Sharding Test App",
    )
    tenant = Tenant(
        id=f"{Tenant.ID_PREFIX}_{suffix}",
        name=f"Tenant {suffix}",
        slug=f"tenant-{suffix}",
        idp_tenant_id=f"org_{suffix}",
    )
    shard = DatabaseShard(
        id=f"{DatabaseShard.ID_PREFIX}_{suffix}",
        name=f"cell_pod_{suffix}",
        dsn="dsn://cell_pod/writer",
        reader_dsn="dsn://cell_pod/reader",
        routing_strategy=ShardRoutingStrategy.VIRTUAL_BUCKET_RING.value,
        status=DatabaseShardStatus.ACTIVE.value,
    )
    registry = ShardRegistry(
        tenant_id=tenant.id,
        app_id=app.id,
        shard_id=shard.id,
        status=DatabaseShardStatus.ACTIVE.value,
    )
    b1 = VirtualBucketAssignment(
        id=f"{VirtualBucketAssignment.ID_PREFIX}_{os.urandom(12).hex()}",
        app_id=app.id,
        bucket_start=0,
        bucket_end=2047,
        shard_id=shard.id,
    )
    b2 = VirtualBucketAssignment(
        id=f"{VirtualBucketAssignment.ID_PREFIX}_{os.urandom(12).hex()}",
        app_id=app.id,
        bucket_start=2048,
        bucket_end=4095,
        shard_id=shard.id,
    )

    async for session in isolated_test_router.get_global_session():
        session.add_all([app, tenant, shard])
        await session.flush()
        session.add_all([registry, b1, b2])
        await session.commit()

        # Verify PostgreSQL CHECK constraint rejects bucket_end >= 4096
        async with session.begin_nested():
            invalid_bucket = VirtualBucketAssignment(
                id=f"{VirtualBucketAssignment.ID_PREFIX}_{os.urandom(12).hex()}",
                app_id=app.id,
                bucket_start=0,
                bucket_end=5000,
                shard_id=shard.id,
            )
            session.add(invalid_bucket)
            with pytest.raises(IntegrityError, match="ck_virtual_bucket_bounds"):
                await session.flush()

    resolver = ShardingProvider.create_tenant_shard_resolver(
        db_router=isolated_test_router,
        app_slug=app_slug,
    )
    tenant_ids = await resolver.get_all_tenant_ids()
    assert tenant_ids == [tenant.id]

    resolved_shard_id, resolved_dsn = await resolver.resolve_shard(tenant.id)
    assert resolved_shard_id == shard.id
    assert resolved_dsn == "dsn://cell_pod/writer"

    subject_outcome = await resolver.resolve_subject_endpoint(tenant.id, "usr_subject_01")
    assert subject_outcome.status == ShardResolutionStatus.RESOLVED
    assert subject_outcome.endpoint is not None
    assert subject_outcome.endpoint.shard_id == shard.id
    assert subject_outcome.endpoint.reader_dsn == "dsn://cell_pod/reader"
