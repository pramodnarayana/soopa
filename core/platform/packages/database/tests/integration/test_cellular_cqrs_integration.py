from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import date
from typing import cast

import pytest
from sharding.domain.constants import DatabaseShardStatus, ShardRoutingStrategy
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.bulk_ingestor import SqlAlchemyBulkRecordIngestor
from database.constants import (
    PartitionCadence,
    PartitionDetachStatus,
)
from database.models.identity import Tenant
from database.models.sharding import DatabaseShard, VirtualBucketAssignment
from database.models.subscriptions import App
from database.partition_manager import (
    RangePartitionLifecycleManager,
    SqlAlchemyPartitionDdlExecutor,
    build_partition_spec,
)
from database.provider import get_async_engine
from database.router import DatabaseRouter
from database.testing import assert_test_database_url
from database.types import TenantSession
from database.uow import BaseSqlAlchemyUnitOfWork
from database.utils import pgbouncer_transaction_connect_args

pytestmark = pytest.mark.integration


class _TestUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """Minimal UnitOfWork bound to savepoint-isolated test session."""


@pytest.fixture
async def isolated_global_session() -> AsyncGenerator[AsyncSession, None]:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        try:
            factory = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                yield session
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


@pytest.mark.integration
async def test_virtual_bucket_assignment_constraints_and_watermark_capture(
    isolated_global_session: AsyncSession,
) -> None:
    suffix = os.urandom(12).hex()
    app = App(
        id=f"{App.ID_PREFIX}_{suffix}",
        slug=f"consumer-app-{suffix}",
        name="Consumer Cellular App",
    )
    shard = DatabaseShard(
        id=f"{DatabaseShard.ID_PREFIX}_{suffix}",
        name=f"cell_pod_{suffix}",
        dsn="dsn://cell_pod/writer",
        reader_dsn="dsn://cell_pod/reader",
        routing_strategy=ShardRoutingStrategy.VIRTUAL_BUCKET_RING.value,
        status=DatabaseShardStatus.ACTIVE.value,
    )
    isolated_global_session.add_all([app, shard])
    await isolated_global_session.flush()

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
    isolated_global_session.add_all([b1, b2])

    uow = _TestUnitOfWork(isolated_global_session)
    with pytest.raises(
        RuntimeError,
        match="Cannot capture replication watermark while a transaction is active",
    ):
        await uow.capture_replication_watermark()
    await uow.commit()
    watermark = await uow.capture_replication_watermark()

    assert int(watermark) > 0
    assert uow.last_commit_watermark == watermark

    rows = (
        (
            await isolated_global_session.execute(
                select(VirtualBucketAssignment)
                .where(VirtualBucketAssignment.app_id == app.id)
                .order_by(VirtualBucketAssignment.bucket_start.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].bucket_end == 2047
    assert rows[1].bucket_start == 2048

    # Verify PostgreSQL CHECK constraint rejects bucket_end >= 4096
    async with isolated_global_session.begin_nested():
        invalid_bucket = VirtualBucketAssignment(
            id=f"{VirtualBucketAssignment.ID_PREFIX}_{os.urandom(12).hex()}",
            app_id=app.id,
            bucket_start=0,
            bucket_end=5000,
            shard_id=shard.id,
        )
        isolated_global_session.add(invalid_bucket)
        with pytest.raises(IntegrityError, match="ck_virtual_bucket_bounds"):
            await isolated_global_session.flush()


@pytest.mark.integration
async def test_database_router_read_session_enforces_readonly_before_rls_without_25001() -> None:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    pg_args = pgbouncer_transaction_connect_args()
    assert pg_args["statement_cache_size"] == 0

    router = DatabaseRouter(
        global_db_url=db_url,
        statement_cache_size=0,
    )
    tenant_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"

    try:
        async for read_session in router.get_tenant_read_session(
            tenant_id=tenant_id,
            pool_key="ucp_shard_test:reader",
            target_dsn=db_url,
        ):
            # 1. Prove RLS GUC was set cleanly AFTER `SET LOCAL TRANSACTION READ ONLY` (no SQLSTATE 25001!)
            guc_res = await read_session.execute(
                text("SELECT current_setting('platform.current_tenant_id', true)")
            )
            assert guc_res.scalar_one() == tenant_id

            # 2. Prove PostgreSQL enforces strict read-only rejection on write attempts!
            with pytest.raises(DBAPIError):
                await read_session.execute(
                    text("CREATE TEMP TABLE forbidden_write_in_read_session (id int)")
                )
    finally:
        await router.close_all()


@pytest.mark.integration
async def test_bulk_record_ingestor_streams_binary_batch_into_postgres(
    isolated_global_session: AsyncSession,
) -> None:
    suffix = os.urandom(6).hex()
    await isolated_global_session.execute(
        text(
            "CREATE TEMP TABLE tmp_bulk_stream_records ("
            "id TEXT NOT NULL, tenant_id TEXT NOT NULL, metric_val INTEGER NOT NULL"
            ") ON COMMIT DROP"
        )
    )
    ingestor = SqlAlchemyBulkRecordIngestor(session=cast(TenantSession, isolated_global_session))
    tenant_id = f"iam_ten_{suffix}"
    count = await ingestor.ingest_batch(
        tenant_id=tenant_id,
        table_name="tmp_bulk_stream_records",
        columns=["id", "tenant_id", "metric_val"],
        records=[
            ("rec_1", tenant_id, 101),
            ("rec_2", tenant_id, 202),
            ("rec_3", tenant_id, 303),
        ],
        schema_name="pg_temp",
    )
    assert count == 3

    guc_res = await isolated_global_session.execute(
        text("SELECT current_setting('platform.current_tenant_id', true)")
    )
    assert guc_res.scalar_one() == tenant_id

    fetched = await isolated_global_session.execute(
        text("SELECT COUNT(*), SUM(metric_val) FROM pg_temp.tmp_bulk_stream_records")
    )
    row = fetched.one()
    assert int(row[0]) == 3
    assert int(row[1]) == 606


@pytest.mark.integration
async def test_range_partition_manager_executes_live_detach_concurrently() -> None:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    suffix = os.urandom(6).hex()
    parent_table = f"part_events_{suffix}"
    ddl_executor = SqlAlchemyPartitionDdlExecutor(engine)
    manager = RangePartitionLifecycleManager(ddl_executor=ddl_executor)

    try:
        await ddl_executor.execute_ddl(
            f'CREATE TABLE "public"."{parent_table}" ('
            "id VARCHAR(64) NOT NULL, "
            "created_at DATE NOT NULL, "
            "PRIMARY KEY (id, created_at)"
            ") PARTITION BY RANGE (created_at)"
        )
        spec_active = build_partition_spec(
            schema_name="public",
            parent_table=parent_table,
            anchor_date=date(2026, 11, 10),
            cadence=PartitionCadence.DAILY,
        )
        spec_old = build_partition_spec(
            schema_name="public",
            parent_table=parent_table,
            anchor_date=date(2026, 10, 1),
            cadence=PartitionCadence.DAILY,
        )
        await manager.ensure_partition(spec_active)
        await manager.ensure_partition(spec_old)
        assert await ddl_executor.partition_exists("public", spec_old.partition_table) is True

        outcome = await manager.retire_partition_non_blocking(
            schema_name="public",
            parent_table=parent_table,
            partition_table=spec_old.partition_table,
        )
        assert outcome.status == PartitionDetachStatus.DETACHED
        assert await ddl_executor.partition_exists("public", spec_old.partition_table) is False
    finally:
        await ddl_executor.execute_ddl(f'DROP TABLE IF EXISTS "public"."{parent_table}" CASCADE')
        await engine.dispose()
