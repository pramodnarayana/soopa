"""Real PostgreSQL narrow integration tests for Universal Control-to-Data Plane Dynamic Watch.

Exercises:
1. `SqlAlchemyConfigChangelogRepository`: atomic append, strictly monotonic BigInt versions,
   wildcard `*` tenant visibility, and chunked CTE cleanup (inside SAVEPOINT rollback).
2. `PostgresNotifyConfigBroadcasterBridge`: live PostgreSQL `LISTEN/NOTIFY` `<200B` pointer
   push -> DB hydration -> `InMemoryRingBufferBroadcaster` real-time fan-out.
3. End-to-end IP Control Plane -> Data Plane Dynamic Watch:
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
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncJobName
from config_sync.provider import ConfigSyncProvider
from database.models.config_sync import ConfigChangelogEntry
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from fastapi import FastAPI
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
from sqlalchemy import delete, update
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


@pytest.mark.integration
async def test_sqlalchemy_config_changelog_monotonic_wildcard_and_chunked_cleanup(
    isolated_session_factory: SessionFactory,
) -> None:
    repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=isolated_session_factory,
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
        tenant_id="*",
        entity_type="as2_partner",
        entity_id="ptr_global",
        action=ConfigChangeAction.UPSERT,
        payload={"id": "ptr_global", "name": "Platform Shared"},
    )
    assert d2.version > d1.version

    latest = await repo.get_latest_version(app_id="edi", tenant_id=tenant_id)
    assert latest == d2.version

    deltas = await repo.get_deltas_since(
        app_id="edi",
        tenant_id=tenant_id,
        since_version=d1.version - 1,
    )
    assert [d.version for d in deltas] == [d1.version, d2.version]
    assert (await repo.get_entry_by_version(version=d2.version)) is not None

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
    assert (await repo.get_entry_by_version(version=d1.version)) is None
    assert (await repo.get_entry_by_version(version=d2.version)) is not None

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
    assert (await repo.get_entry_by_version(version=d2.version)) is None


@pytest.mark.integration
async def test_postgres_notify_broadcaster_bridge_live_push_roundtrip() -> None:
    """Proves real PostgreSQL `LISTEN/NOTIFY` `<200B` pointer push hydrates full delta into broadcaster."""
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    repo = ConfigSyncProvider.create_changelog_repository(session_factory=session_factory)
    broadcaster = ConfigSyncProvider.create_broadcaster()
    bridge = ConfigSyncProvider.create_notify_bridge(
        database_url=db_url,
        changelog_repo=repo,
        broadcaster=broadcaster,
    )

    tenant_id = f"ten_notify_{generate_id(SystemIdPrefix.GENERIC)}"
    created_version: int | None = None
    bridge.start()
    try:
        # Allow asyncpg LISTEN connection to establish
        await asyncio.sleep(0.25)

        async with broadcaster.subscribe(app_id="ip", tenant_id=tenant_id) as sub:
            # Write a payload > 10KB to prove pointer-only NOTIFY bypasses PG's 8KB NOTIFY limit!
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
            assert received.version == delta.version
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
        since_version=snapshot.version,
    )
    assert len(deltas) == 1
    assert deltas[0].action == ConfigChangeAction.DELETE
    assert deltas[0].entity_id == stitch_id

    await ip_sink.apply_delta(deltas[0])
    assert registry.get_stitch(tenant_id=tenant_id, stitch_id=stitch_id) is None
