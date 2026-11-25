"""Comprehensive unit & ASGI end-to-end tests for Universal Control-to-Data Plane Dynamic Watch."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import httpx
import pytest
from config_sync.adapters.inbound.fastapi_watch_router import create_config_sync_router
from config_sync.adapters.inbound.postgres_notify_broadcaster_bridge import (
    PostgresNotifyConfigBroadcasterBridge,
)
from config_sync.adapters.outbound.atomic_in_memory_config_sink import AtomicInMemoryConfigSink
from config_sync.adapters.outbound.httpx_sse_config_watch_client import HttpxSseConfigWatchClient
from config_sync.adapters.outbound.in_memory_ring_buffer_broadcaster import (
    InMemoryRingBufferBroadcaster,
)
from config_sync.application.config_catalog_registry import ConfigCatalogRegistry
from config_sync.application.multi_tenant_watch_manager import MultiTenantConfigWatchManager
from config_sync.application.stream_config_watch_use_case import (
    StreamConfigWatchQuery,
    StreamConfigWatchUseCase,
)
from config_sync.application.sync_config_watch_loop_use_case import (
    SyncConfigWatchLoopUseCase,
    WatchLoopConfig,
)
from config_sync.domain.checksum import compute_payload_checksum, compute_snapshot_checksum
from config_sync.domain.dtos import (
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
    ConfigSyncError,
)
from config_sync.domain.enums import (
    ConfigChangeAction,
    ConfigSyncErrorCode,
    ConfigWatchEventType,
)
from config_sync.domain.monotonic_guard import MonotonicCatalogState
from config_sync.provider import ConfigSyncProvider
from config_sync.testing.fakes import (
    FakeConfigCatalogProvider,
    FakeConfigChangelogRepository,
    FakeConfigWatchClient,
)
from config_sync_worker.provision.settings import WorkerSettings
from fastapi import FastAPI
from ip.engine.adapters.outbound.config_sync.ip_stitch_catalog_sink import IpStitchCatalogSink
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.domain.enums import IP_CONFIG_APP_ID
from ip.engine.domain.stitch.stitch import Stitch
from seedwork.domain.types import JsonDict
from seedwork.infra.config import load_settings_safely


def _make_entity(
    *,
    entity_type: str = "STITCH",
    entity_id: str = "st_1",
    tenant_id: str = "ten_1",
    payload: JsonDict | None = None,
) -> ConfigEntityRecord:
    body: JsonDict = payload or {
        "id": entity_id,
        "tenant_id": tenant_id,
        "canonical_event_type": "order.created",
        "target_workflow_id": "wf_fulfill",
        "name": "Fulfill Order",
        "is_active": True,
    }
    return ConfigEntityRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant_id,
        payload=body,
        checksum=compute_payload_checksum(body),
    )


def _make_delta(
    *,
    app_id: str = "ip",
    tenant_id: str = "ten_1",
    entity_type: str = "STITCH",
    entity_id: str = "st_1",
    action: ConfigChangeAction = ConfigChangeAction.UPSERT,
    version: int = 1,
    payload: JsonDict | None = None,
) -> ConfigDeltaEvent:
    body: JsonDict = payload or {
        "id": entity_id,
        "tenant_id": tenant_id,
        "canonical_event_type": "order.created",
        "target_workflow_id": "wf_fulfill",
        "name": f"Stitch v{version}",
        "is_active": True,
    }
    return ConfigDeltaEvent(
        event_id=f"evt_{version}",
        app_id=app_id,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        version=version,
        checksum=compute_payload_checksum(body),
        payload=body,
    )


def test_monotonic_catalog_state_enforces_checksum_atomic_swap_and_monotonic_guard() -> None:
    state = MonotonicCatalogState(app_id="ip", tenant_id="ten_1")
    rec1 = _make_entity(entity_id="st_1")
    snap = ConfigSnapshot(
        app_id="ip",
        tenant_id="ten_1",
        version=5,
        entities=(rec1,),
        checksum=compute_snapshot_checksum((rec1,)),
    )

    assert state.apply_snapshot(snap).applied is True
    assert state.current_version == 5
    before_view = state.entities
    assert ("STITCH", "ten_1", "st_1") in before_view

    stale_delta = _make_delta(entity_id="st_1", version=5)
    assert state.apply_delta(stale_delta).applied is False
    assert state.current_version == 5

    fresh_delta = _make_delta(entity_id="st_2", version=6)
    assert state.apply_delta(fresh_delta).applied is True
    assert state.current_version == 6
    assert ("STITCH", "ten_1", "st_2") in state.entities
    assert ("STITCH", "ten_1", "st_2") not in before_view

    bad_delta = ConfigDeltaEvent(
        event_id="evt_bad",
        app_id="ip",
        tenant_id="ten_1",
        entity_type="STITCH",
        entity_id="st_3",
        action=ConfigChangeAction.UPSERT,
        version=7,
        checksum="0" * 64,
        payload={"id": "st_3"},
    )
    assert state.apply_delta(bad_delta).applied is False
    assert state.current_version == 6

    del_delta = _make_delta(entity_id="st_1", action=ConfigChangeAction.DELETE, version=8)
    assert state.apply_delta(del_delta).applied is True
    assert state.current_version == 8
    assert state.get_entity("STITCH", "ten_1", "st_1") is None
    assert state.get_entity("STITCH", "ten_1", "st_2") is not None


async def test_ring_buffer_broadcaster_handles_catchup_eviction_and_wildcard_fanout() -> None:
    broadcaster = InMemoryRingBufferBroadcaster(
        ring_buffer_size=3,
        subscriber_queue_maxsize=2,
        broadcast_tenant_ids=("*", "ten_000000000000000000000000"),
    )

    for ver in (1, 2, 3):
        await broadcaster.publish_delta(
            _make_delta(tenant_id="ten_1", entity_id=f"st_{ver}", version=ver)
        )

    caught_up = broadcaster.get_buffered_deltas_since(
        app_id="ip", tenant_id="ten_1", since_version=1
    )
    assert caught_up is not None
    assert [d.version for d in caught_up] == [2, 3]

    for ver in (4, 5):
        await broadcaster.publish_delta(
            _make_delta(tenant_id="ten_1", entity_id=f"st_{ver}", version=ver)
        )

    assert (
        broadcaster.get_buffered_deltas_since(app_id="ip", tenant_id="ten_1", since_version=1)
        is None
    )
    recent = broadcaster.get_buffered_deltas_since(app_id="ip", tenant_id="ten_1", since_version=3)
    assert recent is not None
    assert [d.version for d in recent] == [4, 5]

    async with broadcaster.subscribe(app_id="ip", tenant_id="ten_1") as sub:
        wildcard_delta = _make_delta(tenant_id="*", entity_id="st_shared", version=6)
        await broadcaster.publish_delta(wildcard_delta)
        received = await asyncio.wait_for(sub.__aiter__().__anext__(), timeout=1.0)
        assert received.version == 6
        assert received.tenant_id == "*"

        platform_delta = _make_delta(
            tenant_id="ten_000000000000000000000000", entity_id="st_plat", version=7
        )
        await broadcaster.publish_delta(platform_delta)
        received_plat = await asyncio.wait_for(sub.__aiter__().__anext__(), timeout=1.0)
        assert received_plat.version == 7


async def test_notify_bridge_catch_up_replays_missed_entries_after_overflow_or_disconnect() -> None:
    changelog = FakeConfigChangelogRepository()
    broadcaster = InMemoryRingBufferBroadcaster()
    d1 = await changelog.append_change(
        app_id="ip",
        tenant_id="ten_1",
        entity_type="STITCH",
        entity_id="st_1",
        action=ConfigChangeAction.UPSERT,
        payload={"id": "st_1"},
    )
    d2 = await changelog.append_change(
        app_id="ip",
        tenant_id="ten_1",
        entity_type="STITCH",
        entity_id="st_2",
        action=ConfigChangeAction.UPSERT,
        payload={"id": "st_2"},
    )
    bridge = PostgresNotifyConfigBroadcasterBridge(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        changelog_repo=changelog,
        broadcaster=broadcaster,
    )

    async with broadcaster.subscribe(app_id="ip", tenant_id="ten_1") as sub:
        replayed = await bridge.catch_up_missed_entries()
        assert replayed == 2
        assert bridge.last_dispatched_version == d2.version

        it = sub.__aiter__()
        first = await asyncio.wait_for(it.__anext__(), timeout=1.0)
        second = await asyncio.wait_for(it.__anext__(), timeout=1.0)
        assert [first.version, second.version] == [d1.version, d2.version]


async def test_stream_watch_use_case_streams_chunked_snapshot_dedups_and_catches_up() -> None:
    broadcaster = InMemoryRingBufferBroadcaster()
    changelog = FakeConfigChangelogRepository()
    provider = FakeConfigCatalogProvider(app_id="ip", changelog=changelog)
    for i in range(5):
        payload: JsonDict = {
            "id": f"st_{i}",
            "tenant_id": "ten_1",
            "canonical_event_type": "order.created",
            "target_workflow_id": "wf_fulfill",
            "name": f"Stitch {i}",
            "is_active": True,
        }
        provider.seed_entity(
            tenant_id="ten_1",
            entity_type="STITCH",
            entity_id=f"st_{i}",
            payload=payload,
        )
        await changelog.append_change(
            app_id="ip",
            tenant_id="ten_1",
            entity_type="STITCH",
            entity_id=f"st_{i}",
            action=ConfigChangeAction.UPSERT,
            payload=payload,
        )

    use_case = StreamConfigWatchUseCase(
        registry=ConfigCatalogRegistry(providers=[provider]),
        broadcaster=broadcaster,
    )

    frames = []
    async for frame in use_case.stream(
        provider,
        StreamConfigWatchQuery(
            app_id="ip",
            tenant_id="ten_1",
            since_version=0,
            chunk_size=2,
            max_events=5,
        ),
    ):
        frames.append(frame)

    assert [f.event for f in frames] == [
        ConfigWatchEventType.SNAPSHOT_START.value,
        ConfigWatchEventType.SNAPSHOT_CHUNK.value,
        ConfigWatchEventType.SNAPSHOT_CHUNK.value,
        ConfigWatchEventType.SNAPSHOT_CHUNK.value,
        ConfigWatchEventType.SNAPSHOT_END.value,
    ]
    assert frames[-1].data["final_version"] == 5

    delta_payload: JsonDict = {"id": "st_6", "tenant_id": "ten_1", "name": "Stitch 6"}
    await changelog.append_change(
        app_id="ip",
        tenant_id="ten_1",
        entity_type="STITCH",
        entity_id="st_6",
        action=ConfigChangeAction.UPSERT,
        payload=delta_payload,
    )

    catchup_frames = []
    async for frame in use_case.stream(
        provider,
        StreamConfigWatchQuery(
            app_id="ip",
            tenant_id="ten_1",
            since_version=5,
            max_events=1,
        ),
    ):
        catchup_frames.append(frame)

    assert len(catchup_frames) == 1
    assert catchup_frames[0].event == ConfigWatchEventType.DELTA.value
    assert catchup_frames[0].data["version"] == 6


async def test_atomic_in_memory_sink_lkg_survivability_and_cross_tenant_wildcard_isolation(
    tmp_path: Path,
) -> None:
    lkg_path = tmp_path / "ip_ten_1_lkg.json"
    sink = AtomicInMemoryConfigSink(
        app_id=IP_CONFIG_APP_ID,
        tenant_id="ten_1",
        lkg_file_path=lkg_path,
    )
    rec = _make_entity(entity_id="st_lkg", tenant_id="ten_1")
    snap = ConfigSnapshot(
        app_id=IP_CONFIG_APP_ID,
        tenant_id="ten_1",
        version=12,
        entities=(rec,),
        checksum=compute_snapshot_checksum((rec,)),
    )
    await sink.apply_snapshot(snap)

    assert lkg_path.exists()
    assert stat.S_IMODE(os.stat(lkg_path).st_mode) == 0o600

    # Pre-seed a global wildcard '*' stitch that belongs to all tenants
    registry = InMemoryStitchCatalogRegistry()
    registry.register_stitch(
        Stitch(
            id="st_global_shared",
            tenant_id="*",
            canonical_event_type="order.created",
            target_workflow_id="wf_global",
            name="Global Stitch",
            is_active=True,
        )
    )

    recovered_sink = AtomicInMemoryConfigSink(
        app_id=IP_CONFIG_APP_ID,
        tenant_id="ten_1",
        lkg_file_path=lkg_path,
    )
    ip_sink = IpStitchCatalogSink(
        stitch_catalog=registry,
        backing_sink=recovered_sink,
        tenant_id="ten_1",
    )
    assert registry.get_stitch(tenant_id="ten_1", stitch_id="st_lkg") is not None
    # Global wildcard stitch MUST NOT be deleted by ten_1's snapshot hydration!
    assert registry.get_stitch(tenant_id="ten_other", stitch_id="st_global_shared") is not None

    # Concrete tenant override + delete MUST NOT delete the global wildcard stitch for other tenants!
    await ip_sink.apply_delta(
        _make_delta(entity_id="st_global_shared", tenant_id="ten_1", version=13)
    )
    await ip_sink.apply_delta(
        _make_delta(
            entity_id="st_global_shared",
            tenant_id="ten_1",
            action=ConfigChangeAction.DELETE,
            version=14,
        )
    )
    assert registry.get_stitch(tenant_id="ten_other", stitch_id="st_global_shared") is not None


async def test_fastapi_sse_watch_router_fail_closed_auth_and_first_class_client_results(
    tmp_path: Path,
) -> None:
    """Proves fail-closed 503 when token omitted, 401 on bad token, and first-class Result handling."""
    broadcaster = ConfigSyncProvider.create_broadcaster()
    changelog = FakeConfigChangelogRepository()
    provider = FakeConfigCatalogProvider(app_id=IP_CONFIG_APP_ID, changelog=changelog)
    initial_payload: JsonDict = {
        "id": "st_initial",
        "tenant_id": "ten_42",
        "canonical_event_type": "order.created",
        "target_workflow_id": "wf_fulfill",
        "name": "Initial Stitch",
        "is_active": True,
    }
    provider.seed_entity(
        tenant_id="ten_42",
        entity_type="STITCH",
        entity_id="st_initial",
        payload=initial_payload,
    )
    seed_delta = await changelog.append_change(
        app_id=IP_CONFIG_APP_ID,
        tenant_id="ten_42",
        entity_type="STITCH",
        entity_id="st_initial",
        action=ConfigChangeAction.UPSERT,
        payload=initial_payload,
    )
    stream_uc = ConfigSyncProvider.create_stream_use_case(
        providers=[provider],
        broadcaster=broadcaster,
    )

    # 1. Fail-closed check: omitting token MUST return HTTP 503 (never fail-open!)
    unconfigured_app = FastAPI()
    unconfigured_app.include_router(create_config_sync_router(use_case_provider=lambda: stream_uc))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=unconfigured_app),
        base_url="http://watch.internal",
    ) as uncfg_client:
        resp = await uncfg_client.get(
            "/api/v1/internal/ip/config/snapshot", params={"tenant_id": "ten_42"}
        )
        assert resp.status_code == 503

    # 2. Authenticated router + first-class Result error handling on HttpxSseConfigWatchClient
    app = FastAPI()
    app.include_router(
        create_config_sync_router(
            use_case_provider=lambda: stream_uc,
            internal_bearer_token="super-secret-watch-token",
        )
    )
    transport = httpx.ASGITransport(app=app)

    bad_client = HttpxSseConfigWatchClient(
        base_url="http://watch.internal",
        bearer_token="wrong-token",
        http_transport=transport,
    )
    # First-class error handling: 401 returns Result.fail(UNAUTHORIZED), NEVER raises!
    unauth_snap = await bad_client.fetch_snapshot(app_id=IP_CONFIG_APP_ID, tenant_id="ten_42")
    assert unauth_snap.is_err
    assert unauth_snap.unwrap_err().code == ConfigSyncErrorCode.UNAUTHORIZED

    # Watch stream also yields ConfigSyncError instead of raising RuntimeError!
    watch_items = [
        item async for item in bad_client.watch(app_id=IP_CONFIG_APP_ID, tenant_id="ten_42")
    ]
    assert len(watch_items) == 1
    assert isinstance(watch_items[0], ConfigSyncError)
    assert watch_items[0].code == ConfigSyncErrorCode.UNAUTHORIZED

    # 3. Valid token: 404 unknown app returns Result.fail(UNKNOWN_APP); valid app returns Result.ok
    watch_client = HttpxSseConfigWatchClient(
        base_url="http://watch.internal",
        bearer_token="super-secret-watch-token",
        http_transport=transport,
    )
    missing_app = await watch_client.fetch_snapshot(app_id="nonexistent", tenant_id="ten_42")
    assert missing_app.is_err
    assert missing_app.unwrap_err().code == ConfigSyncErrorCode.UNKNOWN_APP

    snap_res = await watch_client.fetch_snapshot(app_id=IP_CONFIG_APP_ID, tenant_id="ten_42")
    assert snap_res.is_ok
    assert snap_res.unwrap().version == seed_delta.version

    # 4. Full SSE Watch: Cold start snapshot + live delta over ASGITransport
    async def _publish_live_delta() -> None:
        await asyncio.sleep(0.05)
        await broadcaster.publish_delta(
            _make_delta(
                tenant_id="ten_42",
                entity_id="st_pushed_live",
                version=seed_delta.version + 1,
            )
        )

    publisher_task = asyncio.create_task(_publish_live_delta())
    try:
        received_events: list[str] = []
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://watch.internal",
            ) as sse_client,
            sse_client.stream(
                "GET",
                "/api/v1/internal/ip/config/watch",
                params={"tenant_id": "ten_42", "since_version": 0, "max_events": 4},
                headers={"Authorization": "Bearer super-secret-watch-token"},
            ) as response,
        ):
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    received_events.append(line.split(":", 1)[1].strip())
        assert received_events == [
            ConfigWatchEventType.SNAPSHOT_START.value,
            ConfigWatchEventType.SNAPSHOT_CHUNK.value,
            ConfigWatchEventType.SNAPSHOT_END.value,
            ConfigWatchEventType.DELTA.value,
        ]
    finally:
        await publisher_task

    lkg_sink = ConfigSyncProvider.create_in_memory_sink(
        app_id=IP_CONFIG_APP_ID,
        tenant_id="ten_42",
        lkg_file_path=tmp_path / "ten_42.lkg.json",
    )
    registry = InMemoryStitchCatalogRegistry()
    ip_sink = IpStitchCatalogSink(
        stitch_catalog=registry,
        backing_sink=lkg_sink,
        tenant_id="ten_42",
    )
    await ip_sink.apply_snapshot(snap_res.unwrap())
    assert registry.get_stitch(tenant_id="ten_42", stitch_id="st_initial") is not None


async def test_sync_watch_loop_converges_handles_errors_and_rejects_corrupted_frames() -> None:
    rec = _make_entity(entity_id="st_ok", tenant_id="ten_loop")
    valid_snap = ConfigSnapshot(
        app_id="ip",
        tenant_id="ten_loop",
        version=5,
        entities=(rec,),
        checksum=compute_snapshot_checksum((rec,)),
    )
    corrupted_delta = ConfigDeltaEvent(
        event_id="evt_bad",
        app_id="ip",
        tenant_id="ten_loop",
        entity_type="STITCH",
        entity_id="st_bad",
        action=ConfigChangeAction.UPSERT,
        version=6,
        checksum="0" * 64,
        payload={"id": "st_bad"},
    )
    stale_delta = _make_delta(tenant_id="ten_loop", entity_id="st_stale", version=5)
    fresh_delta = _make_delta(tenant_id="ten_loop", entity_id="st_fresh", version=7)
    stream_err = ConfigSyncError(
        code=ConfigSyncErrorCode.STREAM_DISCONNECTED,
        message="Upstream gateway restarted",
    )

    client = FakeConfigWatchClient(
        items=[valid_snap, corrupted_delta, stale_delta, fresh_delta, stream_err]
    )
    sink = AtomicInMemoryConfigSink(app_id="ip", tenant_id="ten_loop")
    loop = SyncConfigWatchLoopUseCase(
        watch_client=client,
        sink=sink,
        config=WatchLoopConfig(app_id="ip", tenant_id="ten_loop"),
    )

    final_version = await loop.sync_once()
    assert final_version == 7
    assert sink.current_version == 7
    assert sink.get_entity("STITCH", "ten_loop", "st_ok") is not None
    assert sink.get_entity("STITCH", "ten_loop", "st_fresh") is not None
    assert sink.get_entity("STITCH", "ten_loop", "st_bad") is None
    assert sink.get_entity("STITCH", "ten_loop", "st_stale") is None


async def test_multi_tenant_watch_manager_discovers_attaches_and_detaches_tenants() -> None:
    active_tenants = ["ten_a", "ten_b"]

    async def _list_tenants() -> list[str]:
        return list(active_tenants)

    fake_client = FakeConfigWatchClient(items=[])
    sinks: dict[str, AtomicInMemoryConfigSink] = {}

    def _sink_factory(tid: str) -> AtomicInMemoryConfigSink:
        sink = AtomicInMemoryConfigSink(app_id="ip", tenant_id=tid)
        sinks[tid] = sink
        return sink

    manager = MultiTenantConfigWatchManager(
        app_id="ip",
        watch_client=fake_client,
        tenant_ids_provider=_list_tenants,
        sink_factory=_sink_factory,
        discovery_interval_seconds=60.0,
    )
    attached = await manager.reconcile_tenants_once()
    assert attached == 2
    assert manager.watched_tenant_ids == ("ten_a", "ten_b")

    active_tenants = ["ten_a", "ten_c"]
    attached_second = await manager.reconcile_tenants_once()
    assert attached_second == 1
    assert manager.watched_tenant_ids == ("ten_a", "ten_c")

    await manager.stop()
    assert len(manager.watched_tenant_ids) == 0


def test_edi_config_sync_worker_settings_boots_with_sovereign_file_storage_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies Finding #4: STORAGE_BACKEND=file no longer crashes WorkerSettings on boot."""
    monkeypatch.setenv("STORAGE_BACKEND", "file")
    monkeypatch.setenv("EDI_ENVIRONMENT", "T")
    monkeypatch.setenv("GLOBAL_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/global_db")
    monkeypatch.setenv("CONFIG_WATCH_BASE_URL", "http://config-watch-gateway:8081")
    monkeypatch.setenv("CONFIG_SYNC_INTERNAL_TOKEN", "sovereign-tok")

    settings = load_settings_safely(WorkerSettings)
    assert settings.config_watch_base_url == "http://config-watch-gateway:8081"
    assert settings.config_watch_token == "sovereign-tok"
