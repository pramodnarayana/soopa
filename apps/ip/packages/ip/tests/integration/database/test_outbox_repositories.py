"""Narrow Integration Tests for SqlAlchemyGlobalOutboxRepository, SqlAlchemyShardedOutboxRepository,
MultiShardOutboxDrainRelay, and IP Worker Module lifecycles against real PostgreSQL.

Runs inside SAVEPOINT-isolated transactions (`transactional_router`, `global_session`, `tenant_session`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.database.data_plane.trace_specs import (
    stage_workflow_outbox_event,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.adapters.outbound.database.models.data_plane import IpDataPlaneOutboxRecord
from ip.engine.adapters.outbound.database.tenant_resolver import SqlAlchemyIpTenantResolver
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
)
from ip.engine.bootstrap.container import (
    create_ip_tenant_uow_provider,
    create_ip_workflow_uow,
)
from ip.engine.bootstrap.workers import (
    IpCpJobsWorkerModule,
    IpDeliveryWorkerModule,
    IpDpJobsWorkerModule,
    IpOrchestratorWorkerModule,
)
from ip.engine.domain.enums import (
    IpEventType,
    IpOutboxSource,
)
from ip.engine.settings import IpEngineSettings
from orchestration.application.services.registries import (
    InMemoryStepHandlerRegistry,
    InMemoryWorkflowDefinitionRegistry,
)
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
)
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.testing.in_memory_event_bus import InMemoryEventBus
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy import select

pytestmark = pytest.mark.integration


class _RecordingPublisher(OutboxPublisherPort):
    """In-memory publisher recording published EventEnvelopes during narrow DB integration tests."""

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        self.published.extend(events)
        return [e.id for e in events]


@pytest.mark.asyncio
async def test_global_outbox_repository_prioritizes_realtime_lane_over_bulk_batches(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyGlobalOutboxRepository prioritizes REALTIME over BULK and marks batches in 1 query."""
    past = datetime.now(UTC) - timedelta(seconds=30)
    bulk_1 = IpOutboxRecord(
        id="cp_out_bulk_1",
        tenant_id="ten_cp_1",
        idempotency_key="idem_cp_bulk_1",
        event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
        trace_id="tr_cp_1",
        correlation_id="corr_cp_1",
        lane=EventProcessingLane.BULK.value,
        payload={"connection_id": "c1", "stream": "s1", "transformation_id": "m1"},
        status=OutboxStatus.PENDING.value,
        created_at=past,
        updated_at=past,
    )
    bulk_2 = IpOutboxRecord(
        id="cp_out_bulk_2",
        tenant_id="ten_cp_1",
        idempotency_key="idem_cp_bulk_2",
        event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
        trace_id="tr_cp_2",
        correlation_id="corr_cp_2",
        lane=EventProcessingLane.BULK.value,
        payload={"connection_id": "c1", "stream": "s2", "transformation_id": "m2"},
        status=OutboxStatus.PENDING.value,
        created_at=past + timedelta(seconds=1),
        updated_at=past + timedelta(seconds=1),
    )
    rt_1 = IpOutboxRecord(
        id="cp_out_rt_1",
        tenant_id="ten_cp_1",
        idempotency_key="idem_cp_rt_1",
        event_type=IpEventType.CONNECTION_CREATED.value,
        trace_id="tr_cp_rt_1",
        correlation_id="corr_cp_rt_1",
        lane=EventProcessingLane.REALTIME.value,
        payload={"connection_id": "c1"},
        status=OutboxStatus.PENDING.value,
        created_at=past + timedelta(seconds=5),
        updated_at=past + timedelta(seconds=5),
    )
    global_session.add_all([bulk_1, bulk_2, rt_1])
    await global_session.flush()

    repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=transactional_router.global_session_scope,
        model_cls=IpOutboxRecord,
        source=IpOutboxSource.CONTROL_PLANE.value,
    )

    claimed = await repo.claim_next_events(
        worker_id="worker_cp_1",
        limit=10,
        lock_lease_ms=30000,
    )
    claimed_ids = [
        e.id for e in claimed if e.id in {"cp_out_bulk_1", "cp_out_bulk_2", "cp_out_rt_1"}
    ]
    assert claimed_ids == ["cp_out_rt_1", "cp_out_bulk_1", "cp_out_bulk_2"]
    assert claimed[0].lane is EventProcessingLane.REALTIME
    assert claimed[0].trace_id == "tr_cp_rt_1"

    await repo.mark_completed_batch(["cp_out_rt_1", "cp_out_bulk_1"], "worker_cp_1")
    await repo.mark_failed_batch(["cp_out_bulk_2"], "worker_cp_1", "Simulated error")

    await global_session.refresh(rt_1)
    await global_session.refresh(bulk_1)
    await global_session.refresh(bulk_2)
    assert rt_1.status == OutboxStatus.PROCESSED.value
    assert bulk_1.status == OutboxStatus.PROCESSED.value
    assert bulk_2.status == OutboxStatus.PENDING.value
    assert bulk_2.error_reason == "Simulated error"


@pytest.mark.asyncio
async def test_sharded_outbox_drain_relay_drains_batches_until_empty(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyShardedOutboxRepository and MultiShardOutboxDrainRelay drain all batches until empty."""
    now = datetime.now(UTC)
    for idx in range(3):
        tenant_session.add(
            IpDataPlaneOutboxRecord(
                id=f"dp_bulk_{idx}",
                tenant_id=seeded_ip_tenant,
                idempotency_key=f"idem_dp_bulk_{idx}",
                event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
                trace_id=f"tr_bulk_{idx}",
                lane=EventProcessingLane.BULK.value,
                payload={
                    "connection_id": "conn_1",
                    "stream": "records_alpha",
                    "record_ids": [f"rep_{idx}_a", f"rep_{idx}_b"],
                },
                status=OutboxStatus.PENDING.value,
                created_at=now + timedelta(milliseconds=idx),
                updated_at=now + timedelta(milliseconds=idx),
            )
        )
    for idx in range(2):
        tenant_session.add(
            IpDataPlaneOutboxRecord(
                id=f"dp_rt_{idx}",
                tenant_id=seeded_ip_tenant,
                idempotency_key=f"idem_dp_rt_{idx}",
                event_type=IpEventType.INBOUND_RECORD_CREATED.value,
                trace_id=f"tr_rt_{idx}",
                lane=EventProcessingLane.REALTIME.value,
                payload={
                    "connection_id": "conn_1",
                    "stream_name": "records_alpha",
                    "record_ids": [f"inb_{idx}"],
                },
                status=OutboxStatus.PENDING.value,
                created_at=now + timedelta(seconds=10 + idx),
                updated_at=now + timedelta(seconds=10 + idx),
            )
        )
    await tenant_session.flush()

    dp_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
    )
    publisher = _RecordingPublisher()
    relay = MultiShardOutboxDrainRelay(
        repository=dp_repo,
        publisher=publisher,
        batch_size=2,
        lock_lease_ms=30000,
    )

    drained_total = await relay.drain_all_shards_once()
    assert drained_total >= 5

    our_published = [
        e
        for e in publisher.published
        if e.id in {"dp_rt_0", "dp_rt_1", "dp_bulk_0", "dp_bulk_1", "dp_bulk_2"}
    ]
    assert [e.id for e in our_published] == [
        "dp_rt_0",
        "dp_rt_1",
        "dp_bulk_0",
        "dp_bulk_1",
        "dp_bulk_2",
    ]


@pytest.mark.asyncio
async def test_global_outbox_repository_sweeps_expired_leases_with_retention_cleanup(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyGlobalOutboxRepository sweeps expired leases and prunes old PROCESSED rows."""
    now = datetime.now(UTC)
    expired_lease = now - timedelta(minutes=10)
    old_processed_ts = now - timedelta(days=20)

    stuck_retryable = IpOutboxRecord(
        id="cp_stuck_retry",
        tenant_id="ten_cp_sweep",
        idempotency_key="idem_cp_stuck_retry",
        event_type=IpEventType.CONNECTION_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"connection_id": "c_retry"},
        status=OutboxStatus.PROCESSING.value,
        attempts=1,
        owner_token="dead_worker_1",
        lease_expires_at=expired_lease,
        created_at=expired_lease,
        updated_at=expired_lease,
    )
    old_processed = IpOutboxRecord(
        id="cp_old_processed",
        tenant_id="ten_cp_sweep",
        idempotency_key="idem_cp_old_processed",
        event_type=IpEventType.CONNECTION_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"connection_id": "c_old"},
        status=OutboxStatus.PROCESSED.value,
        attempts=1,
        published_at=old_processed_ts,
        created_at=old_processed_ts,
        updated_at=old_processed_ts,
    )
    global_session.add_all([stuck_retryable, old_processed])
    await global_session.flush()

    repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=transactional_router.global_session_scope,
        model_cls=IpOutboxRecord,
        source=IpOutboxSource.CONTROL_PLANE.value,
        max_attempts=3,
    )

    swept_count = await repo.sweep_stuck_events(lock_lease_ms=30000)
    assert swept_count >= 1

    await global_session.refresh(stuck_retryable)
    assert stuck_retryable.owner_token is None
    assert stuck_retryable.lease_expires_at is None
    assert stuck_retryable.status == OutboxStatus.PENDING.value

    deleted_count = await repo.cleanup_outbox(retention_days=7)
    assert deleted_count >= 1
    remaining_old = await global_session.execute(
        select(IpOutboxRecord.id).where(IpOutboxRecord.id == "cp_old_processed")
    )
    assert remaining_old.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_sharded_outbox_repository_sweeps_expired_leases_with_retention_cleanup(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyShardedOutboxRepository sweeps expired leases and prunes old PROCESSED rows across shards."""
    now = datetime.now(UTC)
    expired_lease = now - timedelta(minutes=10)
    old_processed_ts = now - timedelta(days=20)

    dp_stuck = IpDataPlaneOutboxRecord(
        id="dp_stuck_retry",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_stuck_retry",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"record_ids": ["inb_1"]},
        status=OutboxStatus.PROCESSING.value,
        attempts=1,
        owner_token="dead_dp_worker",
        lease_expires_at=expired_lease,
        created_at=expired_lease,
        updated_at=expired_lease,
    )
    dp_old_processed = IpDataPlaneOutboxRecord(
        id="dp_old_processed",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_old_processed",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"record_ids": ["inb_old"]},
        status=OutboxStatus.PROCESSED.value,
        attempts=1,
        published_at=old_processed_ts,
        created_at=old_processed_ts,
        updated_at=old_processed_ts,
    )
    tenant_session.add_all([dp_stuck, dp_old_processed])
    await tenant_session.flush()

    dp_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
        max_attempts=3,
    )

    swept = await dp_repo.sweep_stuck_events(lock_lease_ms=30000)
    assert swept >= 1

    cleaned = await dp_repo.cleanup_outbox(retention_days=7)
    assert cleaned >= 1


@pytest.mark.asyncio
async def test_data_plane_uow_releases_claimed_idempotency_key_on_nack(
    seeded_ip_tenant: str,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyIpDataPlaneUnitOfWork claims idempotency keys and releases them on transient NACK."""
    resolver = SqlAlchemyIpTenantResolver(db_router=transactional_router)
    uow_provider = create_ip_tenant_uow_provider(resolver=resolver, db_router=transactional_router)
    shard_res = await uow_provider.resolve_shard_info(seeded_ip_tenant)
    shard_id, shard_dsn = shard_res.unwrap()

    async with uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        assert await uow.record_idempotency(seeded_ip_tenant, "idem_key_nack_test") is True
        await uow.commit()

    async with uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        assert await uow.record_idempotency(seeded_ip_tenant, "idem_key_nack_test") is False

    async with uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.release_idempotency(seeded_ip_tenant, "idem_key_nack_test")
        await uow.commit()

    async with uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        assert await uow.record_idempotency(seeded_ip_tenant, "idem_key_nack_test") is True
        await uow.commit()


@pytest.mark.asyncio
async def test_sharded_outbox_repository_updates_claimed_event_statuses(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify SqlAlchemyShardedOutboxRepository claim_next_events, mark_completed, and mark_failed."""
    now = datetime.now(UTC)
    row_ok = IpDataPlaneOutboxRecord(
        id="dp_claim_ok",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_claim_ok",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"record_ids": ["inb_ok"]},
        status=OutboxStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    row_fail = IpDataPlaneOutboxRecord(
        id="dp_claim_fail",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_claim_fail",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        lane=EventProcessingLane.BULK.value,
        payload={"record_ids": ["inb_fail"]},
        status=OutboxStatus.PENDING.value,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    tenant_session.add_all([row_ok, row_fail])
    await tenant_session.flush()

    dp_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
        max_attempts=3,
    )

    claimed = await dp_repo.claim_next_events(
        worker_id="dp_sweeper_1", limit=10, lock_lease_ms=30000
    )
    claimed_ids = {e.id for e in claimed}
    assert {"dp_claim_ok", "dp_claim_fail"}.issubset(claimed_ids)

    await dp_repo.mark_completed("dp_claim_ok", "dp_sweeper_1")
    await dp_repo.mark_failed("dp_claim_fail", "dp_sweeper_1", "Transient SQS failure")

    await dp_repo.mark_completed_batch(["dp_unknown_id"], "dp_sweeper_1")
    await dp_repo.mark_failed_batch(["dp_unknown_id"], "dp_sweeper_1", "No-op")

    await tenant_session.refresh(row_ok)
    await tenant_session.refresh(row_fail)
    assert row_ok.status == OutboxStatus.PROCESSED.value
    assert row_fail.status == OutboxStatus.PENDING.value
    assert row_fail.error_reason == "Transient SQS failure"


@pytest.mark.asyncio
async def test_stitch_runtime_adapters_dispatch_canonical_events(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify IpStitchCanonicalDispatcherAdapter and IpStitchWorkerTickAdapter against PostgreSQL."""
    stage_workflow_outbox_event(
        tenant_session,
        seeded_ip_tenant,
        IpEventType.OUTBOUND_RECORD_CREATED.value,
        "idem_wf_stage_1",
        {"trace_id": "tr_wf_1", "correlation_id": "corr_wf_1", "record_ids": ["out_wf_1"]},
    )
    await tenant_session.flush()

    resolver = SqlAlchemyIpTenantResolver(db_router=transactional_router)
    dp_uow_provider = create_ip_tenant_uow_provider(
        resolver=resolver, db_router=transactional_router
    )
    stitch_catalog = InMemoryStitchCatalogRegistry()
    def_registry = InMemoryWorkflowDefinitionRegistry()
    handler_registry = InMemoryStepHandlerRegistry()

    stitch_dispatcher = IpStitchCanonicalDispatcherAdapter(
        db_router=transactional_router,
        dp_uow_provider=dp_uow_provider,
        stitch_catalog=stitch_catalog,
        definition_registry=def_registry,
        workflow_uow_factory=create_ip_workflow_uow,
    )
    disp_res = await stitch_dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id=seeded_ip_tenant,
            canonical_event_type="canonical.record_alpha.v1",
            event_id="evt_canon_1",
            payload={"record_id": "REC-1"},
            trace_id="tr_wf_1",
            correlation_id="corr_wf_1",
        )
    )
    assert disp_res.is_ok

    missing_res = await stitch_dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="t_nonexistent",
            canonical_event_type="canonical.record_alpha.v1",
            event_id="evt_canon_2",
            payload={"record_id": "REC-1"},
            trace_id="tr_wf_1",
        )
    )
    assert missing_res.is_err

    stitch_tick = IpStitchWorkerTickAdapter(
        db_router=transactional_router,
        definition_registry=def_registry,
        handler_registry=handler_registry,
        workflow_uow_factory=create_ip_workflow_uow,
    )
    tick_res = await stitch_tick.execute(
        ExecuteStitchWorkerTickCommand(worker_id="w_tick_1", free_slots=5)
    )
    assert tick_res.is_ok


@pytest.mark.asyncio
async def test_ip_worker_modules_manage_background_task_lifecycles(
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify IP LaunchableWorker modules start and stop cleanly against TransactionalTestRouter."""
    settings = IpEngineSettings(
        ip_orchestrator_realtime_queue_url="",
        ip_orchestrator_bulk_queue_url="",
        ip_delivery_realtime_queue_url="",
        ip_delivery_bulk_queue_url="",
        ip_control_plane_jobs_queue_url="",
        ip_data_plane_jobs_queue_url="",
        config_watch_base_url="http://localhost:8081",
        stitch_tick_interval_sec=0.2,
    )
    rt_bus = InMemoryEventBus()
    bulk_bus = InMemoryEventBus()

    orch_module = IpOrchestratorWorkerModule(
        settings=settings,
        db_router=transactional_router,
        realtime_consumer=rt_bus,
        bulk_consumer=bulk_bus,
    )
    await orch_module.start()
    try:
        assert len(orch_module.get_background_tasks()) == 4
    finally:
        await orch_module.stop()

    settings_without_watch = settings.model_copy(update={"config_watch_base_url": ""})
    orch_module_without_watch = IpOrchestratorWorkerModule(
        settings=settings_without_watch,
        db_router=transactional_router,
        realtime_consumer=rt_bus,
        bulk_consumer=bulk_bus,
    )
    await orch_module_without_watch.start()
    try:
        assert len(orch_module_without_watch.get_background_tasks()) == 3
    finally:
        await orch_module_without_watch.stop()

    deliv_module = IpDeliveryWorkerModule(
        settings=settings,
        db_router=transactional_router,
        realtime_consumer=rt_bus,
        bulk_consumer=bulk_bus,
    )
    await deliv_module.start()
    try:
        assert len(deliv_module.get_background_tasks()) == 2
    finally:
        await deliv_module.stop()

    dp_jobs_module = IpDpJobsWorkerModule(
        settings=settings,
        db_router=transactional_router,
        publisher=_RecordingPublisher(),
        jobs_consumer=rt_bus,
    )
    await dp_jobs_module.start()
    try:
        assert len(dp_jobs_module.get_background_tasks()) == 2
    finally:
        await dp_jobs_module.stop()

    cp_jobs_module = IpCpJobsWorkerModule(
        settings=settings,
        db_router=transactional_router,
        publisher=_RecordingPublisher(),
        jobs_consumer=rt_bus,
    )
    await cp_jobs_module.start()
    try:
        assert len(cp_jobs_module.get_background_tasks()) == 2
    finally:
        await cp_jobs_module.stop()


@pytest.mark.asyncio
async def test_sharded_outbox_exclude_filter_skips_excluded_events(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify cross-boundary exclude_event_types skips excluded internal pipeline events."""
    now = datetime.now(UTC)
    internal_evt = IpDataPlaneOutboxRecord(
        id="dp_internal_1",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_internal_1",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        lane=EventProcessingLane.REALTIME.value,
        payload={"record_ids": ["r1"]},
        status=OutboxStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    notif_evt = IpDataPlaneOutboxRecord(
        id="dp_notif_bridge_1",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_notif_bridge_1",
        event_type="notification.requested",
        lane=EventProcessingLane.REALTIME.value,
        payload={"template_id": "alert"},
        status=OutboxStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    tenant_session.add_all([internal_evt, notif_evt])
    await tenant_session.flush()

    bridge_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
        exclude_event_types=(IpEventType.INBOUND_RECORD_CREATED.value,),
    )
    shard_name, shard_dsn = (await bridge_repo.list_shards())[0]

    claimed = await bridge_repo.claim_shard_events(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        worker_id="w_bridge",
        limit=10,
        lock_lease_ms=30000,
    )
    claimed_ids = {e.id for e in claimed}
    assert "dp_notif_bridge_1" in claimed_ids
    assert "dp_internal_1" not in claimed_ids


@pytest.mark.asyncio
async def test_sharded_outbox_retry_backoff_defers_reclaim(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify failed sharded outbox events honor retry backoff before re-claim."""
    now = datetime.now(UTC)
    notif_evt = IpDataPlaneOutboxRecord(
        id="dp_notif_backoff_1",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_notif_backoff_1",
        event_type="notification.requested",
        lane=EventProcessingLane.REALTIME.value,
        payload={"template_id": "alert"},
        status=OutboxStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    tenant_session.add(notif_evt)
    await tenant_session.flush()

    bridge_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
        max_attempts=2,
        base_retry_backoff_seconds=30,
    )
    shard_name, shard_dsn = (await bridge_repo.list_shards())[0]

    claimed = await bridge_repo.claim_shard_events(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        worker_id="w_bridge",
        limit=10,
        lock_lease_ms=30000,
    )
    assert "dp_notif_backoff_1" in {e.id for e in claimed}

    exhausted = await bridge_repo.mark_shard_failed_batch(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        event_ids=["dp_notif_backoff_1"],
        worker_id="w_bridge",
        error_message="Transient error",
        retry_delay_seconds=60,
    )
    assert exhausted == []
    reclaimed_during_backoff = await bridge_repo.claim_shard_events(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        worker_id="w_bridge",
        limit=10,
        lock_lease_ms=30000,
    )
    assert "dp_notif_backoff_1" not in {e.id for e in reclaimed_during_backoff}


@pytest.mark.asyncio
async def test_sharded_outbox_dead_letter_marks_failed(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify terminal dead-lettering marks the sharded outbox row FAILED with error_reason."""
    now = datetime.now(UTC)
    dlq_evt = IpDataPlaneOutboxRecord(
        id="dp_dlq_1",
        tenant_id=seeded_ip_tenant,
        idempotency_key="idem_dp_dlq_1",
        event_type="notification.requested",
        lane=EventProcessingLane.REALTIME.value,
        payload={"template_id": "bad"},
        status=OutboxStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    tenant_session.add(dlq_evt)
    await tenant_session.flush()

    bridge_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
    )
    shard_name, shard_dsn = (await bridge_repo.list_shards())[0]

    await bridge_repo.claim_shard_events(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        worker_id="w_bridge",
        limit=10,
        lock_lease_ms=30000,
    )
    await bridge_repo.mark_shard_dead_letter_batch(
        shard_name=shard_name,
        shard_dsn=shard_dsn,
        event_ids=["dp_dlq_1"],
        worker_id="w_bridge",
        error_message="Poison payload",
    )
    await tenant_session.refresh(dlq_evt)
    assert dlq_evt.status == OutboxStatus.FAILED.value
    assert dlq_evt.error_reason == "Poison payload"
