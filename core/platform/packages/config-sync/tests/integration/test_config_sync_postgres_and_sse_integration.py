"""Real PostgreSQL narrow integration tests for Universal Control-to-Data Plane Dynamic Watch.

Exercises:
1. `SqlAlchemyConfigChangelogRepository`: atomic append, strictly monotonic BigInt versions,
   wildcard `*` tenant visibility, and chunked CTE cleanup (inside SAVEPOINT rollback).
2. `ChangelogCursorBroadcasterBridge`: live linearizable `xid8` Drain-Until-Empty tailing
   and large-payload (>12KB) fan-out into `InMemoryRingBufferBroadcaster`.
3. PostgreSQL MVCC `xid8` Visibility-Barrier concurrency proof: proves uncommitted slow
   transaction T1 + fast committed transaction T2 NEVER skip T1 on live tailing OR cold
   snapshot handoff.
4. End-to-end IP Control Plane -> Data Plane Dynamic Watch:
   `SqlAlchemyStitchRepository` (`save` + `delete`) & `SqlAlchemyMappingSpecRepository` ->
   `config_sync.config_changelog` -> `IpConfigCatalogProvider` -> FastAPI SSE router ->
   `HttpxSseConfigWatchClient` -> `IpStitchCatalogSink` + LKG disk -> `InMemoryStitchCatalogRegistry`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from config_sync.adapters.inbound.fastapi_watch_router import create_config_sync_router
from config_sync.domain.dtos import ConfigCursor
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncJobName
from config_sync.domain.monotonic_guard import MonotonicCatalogState
from config_sync.provider import ConfigSyncProvider
from database.config_changelog import (
    get_latest_config_changelog_cursor_in_session,
    record_config_changelog_entry,
)
from database.models.config_sync import ConfigChangelogEntry
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from fastapi import FastAPI
from identity.domain.identity_context import PLATFORM_TENANT_ID
from ip.engine.adapters.outbound.config_sync.ip_config_catalog_provider import (
    IpConfigCatalogProvider,
)
from ip.engine.adapters.outbound.config_sync.ip_stitch_catalog_sink import IpStitchCatalogSink
from ip.engine.adapters.outbound.database.control_plane.mapping_spec_repository import (
    SqlAlchemyMappingSpecRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stitch_repository import (
    SqlAlchemyStitchRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionRecord
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.domain.enums import IP_CONFIG_APP_ID, IpConfigEntityType
from ip.engine.domain.mapping.enums import MappingRuleType
from ip.engine.domain.mapping.mapping_spec import MappingRule, MappingSpec
from ip.engine.domain.stitch.stitch import Stitch
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob
from scheduler_worker.bootstrap.container import create_job_dispatcher
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@pytest.fixture
async def isolated_session_factory() -> AsyncGenerator[SessionFactory]:
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
            yield factory
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


async def _changelog_version_exists(session_factory: SessionFactory, version: int) -> bool:
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ConfigChangelogEntry.version).where(ConfigChangelogEntry.version == version)
            )
        ).scalar_one_or_none()
        return row is not None


@pytest.mark.integration
async def test_sqlalchemy_config_changelog_monotonic_platform_shared_and_chunked_cleanup(
    isolated_session_factory: SessionFactory,
) -> None:
    repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=isolated_session_factory,
        shared_tenant_ids=(PLATFORM_TENANT_ID,),
    )
    tenant_id = f"ten_cs_{generate_id(SystemIdPrefix.GENERIC)}"

    d1 = await repo.append_change(
        app_id="edi",
        tenant_id=tenant_id,
        entity_type="as2_partner",
        entity_id="ptr_1",
        action=ConfigChangeAction.UPSERT,
        payload={"id": "ptr_1", "name": "Acme"},
    )
    d2 = await repo.append_change(
        app_id="edi",
        tenant_id=PLATFORM_TENANT_ID,
        entity_type="as2_partner",
        entity_id="ptr_global",
        action=ConfigChangeAction.UPSERT,
        payload={"id": "ptr_global", "name": "Platform Shared"},
    )
    assert d2.cursor > d1.cursor

    latest = await repo.get_latest_cursor(app_id="edi", tenant_id=tenant_id)
    assert latest == d2.cursor
    assert (await repo.get_global_safe_cursor()) >= d2.cursor

    deltas = await repo.get_deltas_since(
        app_id="edi",
        tenant_id=tenant_id,
        since_cursor=ConfigCursor(txid=d1.txid, version=d1.version - 1),
    )
    assert [d.cursor for d in deltas] == [d1.cursor, d2.cursor]
    assert await _changelog_version_exists(isolated_session_factory, d2.version)

    # Age d1 beyond retention window and verify chunked CTE cleanup deletes only aged row
    async with isolated_session_factory() as session:
        await session.execute(
            update(ConfigChangelogEntry)
            .where(ConfigChangelogEntry.version == d1.version)
            .values(created_at=datetime.now(UTC) - timedelta(days=45))
        )
        await session.commit()

    deleted = await repo.cleanup_old_entries(retention_days=30)
    assert deleted >= 1
    assert not await _changelog_version_exists(isolated_session_factory, d1.version)
    assert await _changelog_version_exists(isolated_session_factory, d2.version)

    # Verify scheduler-worker `create_job_dispatcher` executes CONFIG_CHANGELOG_CLEANUP in-process!
    async with isolated_session_factory() as session:
        await session.execute(
            update(ConfigChangelogEntry)
            .where(ConfigChangelogEntry.version == d2.version)
            .values(created_at=datetime.now(UTC) - timedelta(days=45))
        )
        await session.commit()

    dispatcher = create_job_dispatcher(
        session_factory=isolated_session_factory,
        queue_url_map={"platform": "db://platform-jobs.fifo"},
    )
    await dispatcher.dispatch(
        ScheduledJob(
            id=generate_id(SystemIdPrefix.GENERIC),
            name=ConfigSyncJobName.CONFIG_CHANGELOG_CLEANUP.value,
            app_namespace="platform",
            payload={"retention_days": 30},
            status=JobStatus.PENDING,
            cron_expression="0 3 * * *",
            target_queue=None,
            interval_seconds=None,
            retry_count=0,
            max_retries=3,
            next_run_at=datetime.now(UTC),
        )
    )
    assert not await _changelog_version_exists(isolated_session_factory, d2.version)


@pytest.mark.integration
async def test_cursor_broadcaster_bridge_live_push_and_large_payload_roundtrip() -> None:
    """Proves linearizable `ChangelogCursorBroadcasterBridge` streams >12KB deltas with zero pg_notify.

    Uses independent committed transactions against `*_test` (rather than a single-connection
    SAVEPOINT) because the background tailer task reads from a separate pooled connection.
    """
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    repo = ConfigSyncProvider.create_changelog_repository(session_factory=session_factory)
    broadcaster = ConfigSyncProvider.create_broadcaster()
    bridge = ConfigSyncProvider.create_cursor_broadcaster_bridge(
        changelog_repo=repo,
        broadcaster=broadcaster,
        poll_interval_seconds=0.05,
    )

    tenant_id = f"ten_cursor_{generate_id(SystemIdPrefix.GENERIC)}"
    created_version: int | None = None
    await bridge.initialize_cursor()
    bridge.start()
    try:
        async with broadcaster.subscribe(app_id="ip", tenant_id=tenant_id) as sub:
            large_payload: JsonDict = {"id": "spec_big", "blob": "X" * 12000}
            delta = await repo.append_change(
                app_id="ip",
                tenant_id=tenant_id,
                entity_type="MAPPING_SPEC",
                entity_id="spec_big",
                action=ConfigChangeAction.UPSERT,
                payload=large_payload,
            )
            created_version = delta.version

            received = await asyncio.wait_for(sub.__aiter__().__anext__(), timeout=5.0)
            assert received.cursor == delta.cursor
            assert received.entity_id == "spec_big"
            assert received.payload["blob"] == "X" * 12000
    finally:
        await bridge.stop()
        if created_version is not None:
            async with session_factory() as cleanup_session:
                await cleanup_session.execute(
                    delete(ConfigChangelogEntry).where(
                        ConfigChangelogEntry.version == created_version
                    )
                )
                await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.integration
async def test_xid8_visibility_barrier_prevents_mvcc_sequence_gap_loss_and_snapshot_race() -> None:
    """Mathematical MVCC proof on live PostgreSQL 16: slow uncommitted T1 (v=N) + fast committed T2 (v=N+1).

    Requires independent PostgreSQL connections (not a single-connection SAVEPOINT) to exercise
    true cross-transaction `pg_snapshot_xmin(pg_current_snapshot())` MVCC visibility barriers.
    """
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    repo = ConfigSyncProvider.create_changelog_repository(session_factory=session_factory)
    broadcaster = ConfigSyncProvider.create_broadcaster()
    baseline_cursor = await repo.get_global_safe_cursor()
    bridge = ConfigSyncProvider.create_cursor_broadcaster_bridge(
        changelog_repo=repo,
        broadcaster=broadcaster,
        initial_cursor=baseline_cursor,
    )

    tenant_id = f"ten_mvcc_{generate_id(SystemIdPrefix.GENERIC)}"
    created_versions: list[int] = []
    try:
        async with session_factory() as session_t1:
            e1 = await record_config_changelog_entry(
                session_t1,
                event_id=generate_id(SystemIdPrefix.GENERIC),
                app_id="edi",
                tenant_id=tenant_id,
                entity_type="as2_partner",
                entity_id="slow_t1",
                action=ConfigChangeAction.UPSERT.value,
                checksum="a" * 64,
                payload={"id": "slow_t1"},
            )
            v1 = int(e1.version)
            created_versions.append(v1)

            async with session_factory() as session_t2:
                e2 = await record_config_changelog_entry(
                    session_t2,
                    event_id=generate_id(SystemIdPrefix.GENERIC),
                    app_id="edi",
                    tenant_id=tenant_id,
                    entity_type="as2_partner",
                    entity_id="fast_t2",
                    action=ConfigChangeAction.UPSERT.value,
                    checksum="b" * 64,
                    payload={"id": "fast_t2"},
                )
                v2 = int(e2.version)
                created_versions.append(v2)
                await session_t2.commit()

            assert v2 > v1

            # 1. Visibility barrier MUST hold back T2 while T1 is uncommitted
            published_while_t1_open = await bridge.poll_once()
            assert published_while_t1_open == 0
            assert bridge.last_dispatched_cursor == baseline_cursor

            # 2. Visibility lag telemetry MUST detect raw_max_cursor > safe_cursor
            watermark = await repo.get_visibility_lag_metrics()
            assert watermark.is_lagged is True
            assert watermark.raw_max_version >= v2
            assert watermark.safe_version < v1

            # 3. Cold snapshot cursor taken during open T1 MUST stay strictly below T1
            async with session_factory() as snapshot_session:
                snap_txid, snap_ver = await get_latest_config_changelog_cursor_in_session(
                    snapshot_session,
                    app_id="edi",
                    tenant_id=tenant_id,
                )
            snapshot_cursor = ConfigCursor(txid=snap_txid, version=snap_ver)
            assert snapshot_cursor.version < v1

            # 4. Now commit slow transaction T1
            await session_t1.commit()

        # 5. Drain emits BOTH [v1, v2] in strictly increasing `(txid, version)` order
        async with broadcaster.subscribe(app_id="edi", tenant_id=tenant_id) as sub:
            drained = await bridge.drain_until_empty()
            assert drained == 2
            assert bridge.last_dispatched_version == v2

            it = sub.__aiter__()
            first = await asyncio.wait_for(it.__anext__(), timeout=2.0)
            second = await asyncio.wait_for(it.__anext__(), timeout=2.0)
            assert [(first.version, first.entity_id), (second.version, second.entity_id)] == [
                (v1, "slow_t1"),
                (v2, "fast_t2"),
            ]

        # 6. Cold snapshot catch-up from `snapshot_cursor` delivers BOTH [v1, v2]
        catchup = await repo.get_deltas_since(
            app_id="edi",
            tenant_id=tenant_id,
            since_cursor=snapshot_cursor,
        )
        assert [(d.version, d.entity_id) for d in catchup] == [
            (v1, "slow_t1"),
            (v2, "fast_t2"),
        ]
    finally:
        if created_versions:
            async with session_factory() as cleanup_session:
                await cleanup_session.execute(
                    delete(ConfigChangelogEntry).where(
                        ConfigChangelogEntry.version.in_(created_versions)
                    )
                )
                await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.integration
async def test_composite_txid_version_cursor_prevents_txid_vs_sequence_interleaving_loss() -> None:
    """Reproduces the exact B1 formal counterexample on live PostgreSQL 16.

    1. T1 acquires `txid_1` FIRST (simulating a preceding `UPDATE` statement).
    2. T2 acquires `txid_2 > txid_1` and inserts `version_1` (uncommitted).
    3. T1 (`txid_1`) inserts `version_2 > version_1` and COMMITS FIRST.
    4. Tailer polls while T2 is open -> emits `(txid_1, version_2)` and advances cursor.
    5. T2 commits `(txid_2, version_1)`.
    6. Tailer polls again -> emits `(txid_2, version_1)` (NOT LOST!) and client
       `MonotonicCatalogState` accepts BOTH entries in `(txid, version)` total order!

    Requires independent PostgreSQL connections (not a single-connection SAVEPOINT) to create
    interleaved concurrent `xid8` transaction IDs.
    """
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    repo = ConfigSyncProvider.create_changelog_repository(session_factory=session_factory)
    broadcaster = ConfigSyncProvider.create_broadcaster()
    baseline_cursor = await repo.get_global_safe_cursor()
    bridge = ConfigSyncProvider.create_cursor_broadcaster_bridge(
        changelog_repo=repo,
        broadcaster=broadcaster,
        initial_cursor=baseline_cursor,
    )

    tenant_id = f"ten_b1_{generate_id(SystemIdPrefix.GENERIC)}"
    created_versions: list[int] = []
    client_state = MonotonicCatalogState(app_id="edi", tenant_id=tenant_id)
    try:
        async with broadcaster.subscribe(app_id="edi", tenant_id=tenant_id) as sub:
            it = sub.__aiter__()
            async with session_factory() as session_t1:
                # Step 1: T1 allocates txid_1 FIRST (like `UPDATE as2_partners` before changelog insert)
                t1_txid = int(
                    (await session_t1.execute(select(func.pg_current_xact_id()))).scalar_one()
                )

                # Step 2: T2 starts SECOND, allocates txid_2 > txid_1, and inserts version_1 (uncommitted!)
                async with session_factory() as session_t2:
                    d_t2 = await repo.append_change_in_session(
                        session_t2,
                        app_id="edi",
                        tenant_id=tenant_id,
                        entity_type="as2_partner",
                        entity_id="t2_lower_seq",
                        action=ConfigChangeAction.UPSERT,
                        payload={"id": "t2_lower_seq"},
                    )
                    created_versions.append(d_t2.version)

                    # Step 3: T1 (lower txid_1!) inserts higher version_2 and COMMITS FIRST!
                    d_t1 = await repo.append_change_in_session(
                        session_t1,
                        app_id="edi",
                        tenant_id=tenant_id,
                        entity_type="as2_partner",
                        entity_id="t1_higher_seq",
                        action=ConfigChangeAction.UPSERT,
                        payload={"id": "t1_higher_seq"},
                    )
                    created_versions.append(d_t1.version)
                    await session_t1.commit()

                    assert d_t1.txid == t1_txid
                    assert d_t1.txid < d_t2.txid
                    assert d_t1.version > d_t2.version  # The exact B1 counterexample!

                    # Step 4: Poll while T2 is still open -> emits T1 (txid_1, higher version_2)
                    assert await bridge.drain_until_empty() == 1
                    first = await asyncio.wait_for(it.__anext__(), timeout=2.0)
                    assert first.entity_id == "t1_higher_seq"
                    assert client_state.apply_delta(first).applied is True

                    # Step 5: Now T2 (txid_2, LOWER version_1!) commits
                    await session_t2.commit()

            # Step 6: Next poll MUST emit T2 (NEVER skipped!) and MonotonicCatalogState MUST accept it!
            assert await bridge.drain_until_empty() == 1
            second = await asyncio.wait_for(it.__anext__(), timeout=2.0)
            assert second.entity_id == "t2_lower_seq"
            assert second.version < first.version
            assert second.cursor > first.cursor
            assert client_state.apply_delta(second).applied is True
            assert client_state.get_entity("as2_partner", tenant_id, "t1_higher_seq") is not None
            assert client_state.get_entity("as2_partner", tenant_id, "t2_lower_seq") is not None
    finally:
        if created_versions:
            async with session_factory() as cleanup_session:
                await cleanup_session.execute(
                    delete(ConfigChangelogEntry).where(
                        ConfigChangelogEntry.version.in_(created_versions)
                    )
                )
                await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.integration
async def test_ip_control_plane_to_data_plane_dynamic_watch_end_to_end(
    isolated_session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    """Full IP Control Plane -> PostgreSQL Changelog -> SSE Watch -> Data Plane Stitch Registry & LKG."""
    tenant_id = f"ten_ip_watch_{generate_id(SystemIdPrefix.GENERIC)}"
    conn_id = f"conn_{generate_id(SystemIdPrefix.GENERIC)}"
    stitch_id = f"st_{generate_id(SystemIdPrefix.GENERIC)}"
    spec_id = f"ms_{generate_id(SystemIdPrefix.GENERIC)}"

    # 1. Control Plane writes parent Connection + Stitch + MappingSpec in PostgreSQL (atomically emits ConfigChangelogEntry)
    async with isolated_session_factory() as session:
        session.info["session_type"] = "global"
        now = datetime.now(UTC)
        session.add(
            ConnectionRecord(
                id=conn_id,
                tenant_id=tenant_id,
                app_id="shopify",
                name="Shopify Store",
                auth_type="NO_AUTH",
                public_config={},
                encrypted_credentials=None,
                key_encryption_version=1,
                connection_fingerprint=f"fp_{conn_id}",
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        stitch_repo = SqlAlchemyStitchRepository(session)
        spec_repo = SqlAlchemyMappingSpecRepository(session)

        await spec_repo.save(
            MappingSpec(
                id=spec_id,
                tenant_id=tenant_id,
                name="Order Map",
                description="Maps orders",
                source_type="shopify",
                target_connection_id=conn_id,
                target_entity_name="Order",
                version=1,
                rules=(
                    MappingRule(
                        target_field="external_id",
                        rule_type=MappingRuleType.DIRECT,
                        source_field="id",
                    ),
                ),
                is_active=True,
            )
        )
        await stitch_repo.save(
            Stitch(
                id=stitch_id,
                tenant_id=tenant_id,
                name="Shopify Order Sync",
                description="Syncs orders",
                mapping_spec_id=spec_id,
                canonical_event_type="shopify.order.created",
                target_workflow_id="wf_sync_order",
                filter_conditions={"channel": "web"},
                is_active=True,
            )
        )
        await session.commit()

    # 2. Mount Universal Watch Router backed by IpConfigCatalogProvider
    changelog_repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=isolated_session_factory
    )
    ip_provider = IpConfigCatalogProvider(
        session_factory=isolated_session_factory,
        changelog_repo=changelog_repo,
    )
    broadcaster = ConfigSyncProvider.create_broadcaster()
    stream_uc = ConfigSyncProvider.create_stream_use_case(
        providers=[ip_provider],
        broadcaster=broadcaster,
    )
    app = FastAPI()
    app.include_router(
        create_config_sync_router(
            use_case_provider=lambda: stream_uc,
            internal_bearer_token="tok",
        )
    )
    transport = httpx.ASGITransport(app=app)

    # 3. Data Plane fetches initial snapshot & hydrates InMemoryStitchCatalogRegistry + LKG disk
    watch_client = ConfigSyncProvider.create_sse_watch_client(
        base_url="http://cp.internal",
        bearer_token="tok",
        http_transport=transport,
    )
    lkg_file = tmp_path / f"{tenant_id}_ip_lkg.json"
    lkg_sink = ConfigSyncProvider.create_in_memory_sink(
        app_id=IP_CONFIG_APP_ID,
        tenant_id=tenant_id,
        lkg_file_path=lkg_file,
    )
    registry = InMemoryStitchCatalogRegistry()
    ip_sink = IpStitchCatalogSink(
        stitch_catalog=registry,
        backing_sink=lkg_sink,
        tenant_id=tenant_id,
    )

    snapshot_res = await watch_client.fetch_snapshot(app_id=IP_CONFIG_APP_ID, tenant_id=tenant_id)
    assert snapshot_res.is_ok
    snapshot = snapshot_res.unwrap()
    assert snapshot.version > 0
    await ip_sink.apply_snapshot(snapshot)

    hydrated = registry.get_stitch(tenant_id=tenant_id, stitch_id=stitch_id)
    assert hydrated is not None
    assert hydrated.target_workflow_id == "wf_sync_order"
    assert len(lkg_sink.list_by_type(IpConfigEntityType.MAPPING_SPEC.value)) == 1
    assert lkg_file.exists()

    # 4. Control Plane deletes Stitch -> Data Plane receives monotonic DELETE delta via catch-up
    async with isolated_session_factory() as session:
        session.info["session_type"] = "global"
        stitch_repo = SqlAlchemyStitchRepository(session)
        await stitch_repo.delete(tenant_id=tenant_id, stitch_id=stitch_id)
        await session.commit()

    deltas = await ip_provider.get_deltas_since(
        tenant_id=tenant_id,
        since_cursor=snapshot.cursor,
    )
    assert len(deltas) == 1
    assert deltas[0].action == ConfigChangeAction.DELETE
    assert deltas[0].entity_id == stitch_id

    await ip_sink.apply_delta(deltas[0])
    assert registry.get_stitch(tenant_id=tenant_id, stitch_id=stitch_id) is None
