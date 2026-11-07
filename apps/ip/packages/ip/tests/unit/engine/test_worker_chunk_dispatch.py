"""Unit tests for IP Engine worker route registries, outbox routers, and job worker modules."""

from __future__ import annotations

import asyncio
import json

import pytest
from helpers.worker_fakes import (
    FakeBackfillExecutor,
    FakeDataPlaneUoW,
    FakeDataPlaneUoWProvider,
    FakeFetchRecordExecutor,
    FakeNormalizeExecutor,
    FakeOutboundDeliveryExecutor,
    FakeOutboxPublisher,
    FakeOutboxRepository,
    FakeRunSyncExecutor,
    FakeStitchDispatcher,
    FakeStitchTickExecutor,
    FakeTieredStorage,
    FakeTraceRetentionRepository,
    make_outbound_record,
    make_stream_definition,
)
from ip.engine.adapters.inbound.workers import (
    IpDeliveryRouteRegistry,
    IpMultiShardStitchTickLoop,
    IpOrchestratorRouteRegistry,
)
from ip.engine.bootstrap.publisher_factory import (
    build_ip_cp_outbox_router,
    build_ip_dp_outbox_router,
)
from ip.engine.bootstrap.workers import (
    IpCpJobsWorkerModule,
    IpDeliveryWorkerModule,
    IpDpJobsWorkerModule,
    IpOrchestratorWorkerModule,
)
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.enums import IpEventType, IpJobName
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.replication.enums import IngestionMode, SyncRunStatus
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.settings import IpEngineSettings
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.enums import ConsumerAction
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope, EventProcessingLane
from strace.application.clean_trace_retention_use_case import CleanTraceRetentionUseCase
from unified_worker.registry import get_worker_instance


@pytest.mark.asyncio
async def test_orchestrator_route_registry_replicates_inbound_chunk_idempotently() -> None:
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()

    for idx in (1, 2):
        body: JsonDict = {
            "record_id": f"REC-{idx}",
            "quantity": 10.5 * idx,
            "updated_at": "2026-10-27T00:00:00Z",
        }
        raw_bytes = json.dumps(body).encode("utf-8")
        rec = InboundRecord.create(
            tenant_id="t_01",
            connection_id="conn_01",
            app_id="acme_source",
            stream_name="records_alpha",
            payload_bytes=raw_bytes,
            is_inlined=True,
            request_body=body,
            trace_id="tr_01",
            ingestion_mode=IngestionMode.PUSH_FULL,
        )
        rec.id = f"inb_{idx}"
        uow.inbound_records.records[f"inb_{idx}"] = rec

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=FakeNormalizeExecutor(),
        backfill_use_case=FakeBackfillExecutor(),
        tiered_storage=storage,
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
        stream_definition_resolver=lambda t, c, s: make_stream_definition(),
        max_chunk_concurrency=4,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    envelope = EventEnvelope(
        id="evt_inb_bulk_1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_inb_bulk_1",
        trace_id="tr_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream_name": "records_alpha",
            "record_ids": ["inb_1", "inb_2"],
        },
    )
    action = await dispatcher.dispatch_envelope(envelope)
    assert action == ConsumerAction.ACK
    assert len(uow.replica_records.merged_candidates) == 2
    assert ("t_01", "idem_evt_inb_bulk_1") in uow.committed_idempotency_keys

    prev_commits = uow.commit_count
    dup_action = await dispatcher.dispatch_envelope(envelope)
    assert dup_action == ConsumerAction.ACK
    assert uow.commit_count == prev_commits


@pytest.mark.asyncio
async def test_orchestrator_route_registry_bounds_normalize_concurrency() -> None:
    uow = FakeDataPlaneUoW()
    normalize_exec = FakeNormalizeExecutor(delay_seconds=0.015)

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        normalize_use_case=normalize_exec,
        backfill_use_case=FakeBackfillExecutor(),
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
        max_chunk_concurrency=3,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    rep_ids: list[JsonValue] = [f"rep_{i}" for i in range(10)]
    bulk_envelope = EventEnvelope(
        id="evt_rep_bulk_10",
        source="ip.data_plane",
        event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_rep_bulk_10",
        trace_id="tr_bulk_10",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
            "record_ids": rep_ids,
        },
    )
    action = await dispatcher.dispatch_envelope(bulk_envelope)
    assert action == ConsumerAction.ACK
    assert len(normalize_exec.executed_ids) == 10
    assert 1 < normalize_exec.max_observed_in_flight <= 3


@pytest.mark.asyncio
async def test_orchestrator_route_registry_rolls_back_idempotency_on_normalize_nack() -> None:
    uow = FakeDataPlaneUoW()
    normalize_exec = FakeNormalizeExecutor(fail_ids={"rep_fail"}, delay_seconds=0.005)

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        normalize_use_case=normalize_exec,
        backfill_use_case=FakeBackfillExecutor(),
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
        max_chunk_concurrency=3,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    fail_envelope = EventEnvelope(
        id="evt_rep_fail",
        source="ip.data_plane",
        event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_rep_fail",
        trace_id="tr_fail",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
            "record_ids": ["rep_ok", "rep_fail"],
        },
    )
    fail_action = await dispatcher.dispatch_envelope(fail_envelope)
    assert fail_action == ConsumerAction.NACK
    assert uow.release_count >= 1
    assert ("t_01", "idem_rep_fail") not in uow.committed_idempotency_keys


@pytest.mark.asyncio
async def test_orchestrator_route_registry_dispatches_canonical_stitches() -> None:
    uow = FakeDataPlaneUoW()
    stitch_disp = FakeStitchDispatcher(started_run_ids=("wf_run_01",))
    stitch_tick = FakeStitchTickExecutor()

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        normalize_use_case=FakeNormalizeExecutor(),
        backfill_use_case=FakeBackfillExecutor(),
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=stitch_disp,
        stitch_worker_tick=stitch_tick,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    canon_env = EventEnvelope(
        id="evt_canon_1",
        source="ip.data_plane",
        event_type=IpEventType.CANONICAL_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_canon_1",
        trace_id="tr_canon_1",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "canonical_type": "canonical.record_alpha.v1",
            "record_ids": ["REC-1", "REC-2"],
        },
    )
    assert await dispatcher.dispatch_envelope(canon_env) == ConsumerAction.ACK
    assert len(stitch_disp.commands) == 2
    assert len(stitch_tick.commands) == 2


@pytest.mark.asyncio
async def test_orchestrator_route_registry_handles_generation_completed_sweep() -> None:
    uow = FakeDataPlaneUoW()
    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        normalize_use_case=FakeNormalizeExecutor(),
        backfill_use_case=FakeBackfillExecutor(),
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    gen_env = EventEnvelope(
        id="evt_gen_1",
        source="ip.data_plane",
        event_type=IpEventType.GENERATION_COMPLETED.value,
        tenant_id="t_01",
        idempotency_key="idem_gen_1",
        trace_id="tr_gen_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
            "generation_id": 5,
        },
    )
    assert await dispatcher.dispatch_envelope(gen_env) == ConsumerAction.ACK


@pytest.mark.asyncio
async def test_orchestrator_route_registry_handles_transformation_promoted_backfill() -> None:
    uow = FakeDataPlaneUoW()
    backfill_exec = FakeBackfillExecutor()
    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        normalize_use_case=FakeNormalizeExecutor(),
        backfill_use_case=backfill_exec,
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    bf_env = EventEnvelope(
        id="evt_bf_1",
        source="ip.control_plane",
        event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
        tenant_id="t_01",
        idempotency_key="idem_bf_1",
        trace_id="tr_bf_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
            "transformation_id": "map_01",
        },
    )
    assert await dispatcher.dispatch_envelope(bf_env) == ConsumerAction.ACK
    assert len(backfill_exec.commands) == 1


@pytest.mark.asyncio
async def test_orchestrator_route_registry_handles_secondary_events_with_dlq_for_missing_shard() -> (
    None
):
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow, missing_tenant_ids={"t_missing"})
    backfill_exec = FakeBackfillExecutor()

    orch_reg = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=FakeNormalizeExecutor(),
        backfill_use_case=backfill_exec,
        tiered_storage=FakeTieredStorage(),
        stitch_dispatcher=FakeStitchDispatcher(),
        stitch_worker_tick=FakeStitchTickExecutor(),
    )
    dispatcher = EventEnvelopeDispatcher()
    orch_reg.register_routes(dispatcher)

    norm_rec = NormalizedRecord.create(
        tenant_id="t_01",
        connection_id="conn_01",
        canonical_type="canonical.record_alpha.v1",
        source_id="REC-55",
        canonical_data={"record_id": "REC-55", "quantity": 42.0},
        trace_id="tr_norm_1",
    )
    norm_rec.id = "norm_55"
    uow.normalized_records.records["norm_55"] = norm_rec

    norm_env = EventEnvelope(
        id="evt_norm_55",
        source="ip.data_plane",
        event_type=IpEventType.NORMALIZED_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_norm_55",
        trace_id="tr_norm_1",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "canonical_type": "canonical.record_alpha.v1",
            "source_id": "REC-55",
            "record_ids": ["norm_55"],
        },
    )
    assert await dispatcher.dispatch_envelope(norm_env) == ConsumerAction.ACK

    mb_env = EventEnvelope(
        id="evt_mb_1",
        source="ip.control_plane",
        event_type=IpEventType.TRANSFORMATION_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_mb_1",
        trace_id="tr_mb_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
            "transformation_id": "map_02",
        },
    )
    assert await dispatcher.dispatch_envelope(mb_env) == ConsumerAction.ACK
    assert len(backfill_exec.commands) == 1

    missing_env = EventEnvelope(
        id="evt_missing_shard",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_missing",
        idempotency_key="idem_missing",
        payload={
            "connection_id": "conn_01",
            "stream_name": "records_alpha",
            "record_ids": ["inb_1"],
        },
    )
    assert await dispatcher.dispatch_envelope(missing_env) == ConsumerAction.DLQ


@pytest.mark.asyncio
async def test_delivery_route_registry_hydrates_pending_outbound_chunks_with_bounded_concurrency() -> (
    None
):
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()

    s3_body = {"invoice_id": "INV-S3", "total": 999.0}
    storage.blobs["s3://ip/out_s3.json"] = json.dumps(s3_body).encode("utf-8")

    uow.outbound_records.records["out_1"] = make_outbound_record("out_1")
    uow.outbound_records.records["out_2"] = make_outbound_record("out_2")
    uow.outbound_records.records["out_3"] = make_outbound_record("out_3")
    uow.outbound_records.records["out_s3"] = make_outbound_record(
        "out_s3",
        is_inlined=False,
        request_body=None,
        request_s3_key="s3://ip/out_s3.json",
    )
    uow.outbound_records.records["out_already_delivered"] = make_outbound_record(
        "out_already_delivered",
        status=OutboundDispatchStatus.DELIVERED,
    )

    delivery_exec = FakeOutboundDeliveryExecutor(delay_seconds=0.015)
    registry = IpDeliveryRouteRegistry(
        dp_uow_provider=uow_provider,
        deliver_outbound_use_case=delivery_exec,
        fetch_record_use_case=FakeFetchRecordExecutor(),
        run_sync_use_case=FakeRunSyncExecutor(status=SyncRunStatus.SUCCEEDED.value),
        tiered_storage=storage,
        max_chunk_concurrency=2,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    out_env = EventEnvelope(
        id="evt_out_chunk_1",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_out_chunk_1",
        trace_id="tr_out_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": [
                "out_1",
                "out_2",
                "out_3",
                "out_s3",
                "out_already_delivered",
            ],
        },
    )
    action = await dispatcher.dispatch_envelope(out_env)
    assert action == ConsumerAction.ACK
    dispatched_ids = [cmd.record_id for cmd in delivery_exec.commands]
    assert sorted(str(x) for x in dispatched_ids) == ["out_1", "out_2", "out_3", "out_s3"]
    s3_cmd = next(cmd for cmd in delivery_exec.commands if cmd.record_id == "out_s3")
    assert s3_cmd.payload == {"invoice_id": "INV-S3", "total": 999.0}
    assert 1 < delivery_exec.max_observed_in_flight <= 2


@pytest.mark.asyncio
async def test_delivery_route_registry_dispatches_fetch_record_chunks() -> None:
    uow = FakeDataPlaneUoW()
    fetch_exec = FakeFetchRecordExecutor()
    registry = IpDeliveryRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        deliver_outbound_use_case=FakeOutboundDeliveryExecutor(),
        fetch_record_use_case=fetch_exec,
        run_sync_use_case=FakeRunSyncExecutor(),
        tiered_storage=FakeTieredStorage(),
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    fetch_env = EventEnvelope(
        id="evt_fetch_1",
        source="ip.data_plane",
        event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_fetch_1",
        trace_id="tr_fetch_01",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "stream": "orders",
            "record_ids": ["ORD-10", "ORD-11"],
            "notice_inbound_record_id": "inb_notice_1",
        },
    )
    assert await dispatcher.dispatch_envelope(fetch_env) == ConsumerAction.ACK
    assert [c.record_id for c in fetch_exec.commands] == ["ORD-10", "ORD-11"]


@pytest.mark.asyncio
async def test_delivery_route_registry_maps_sync_run_outcomes_to_consumer_actions() -> None:
    uow = FakeDataPlaneUoW()
    sync_exec = FakeRunSyncExecutor(status=SyncRunStatus.SUCCEEDED.value)
    registry = IpDeliveryRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        deliver_outbound_use_case=FakeOutboundDeliveryExecutor(),
        fetch_record_use_case=FakeFetchRecordExecutor(),
        run_sync_use_case=sync_exec,
        tiered_storage=FakeTieredStorage(),
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    sync_env = EventEnvelope(
        id="evt_sync_1",
        source="ip.control_plane",
        event_type=IpEventType.SYNC_RUN_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_sync_1",
        trace_id="tr_sync_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "records_alpha",
        },
    )
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.ACK

    sync_exec.status = SyncRunStatus.FAILED.value
    sync_exec.error_code = "RATE_LIMITED"
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.NACK

    sync_exec.error_code = "AUTH_INVALID"
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.DLQ


@pytest.mark.asyncio
async def test_delivery_route_registry_maps_outbound_failure_dispositions() -> None:
    uow = FakeDataPlaneUoW()
    uow.outbound_records.records["out_rl"] = make_outbound_record("out_rl")
    uow.outbound_records.records["out_term"] = make_outbound_record("out_term")
    deliv_exec = FakeOutboundDeliveryExecutor(
        status_by_key={
            "idem_out_rl": OutboundDispatchStatus.RETRY_SCHEDULED,
            "idem_out_term": OutboundDispatchStatus.FAILED,
        }
    )
    deliv_reg = IpDeliveryRouteRegistry(
        dp_uow_provider=FakeDataPlaneUoWProvider(uow),
        deliver_outbound_use_case=deliv_exec,
        fetch_record_use_case=FakeFetchRecordExecutor(status="RATE_LIMITED"),
        run_sync_use_case=FakeRunSyncExecutor(),
        tiered_storage=FakeTieredStorage(),
    )
    deliv_disp = EventEnvelopeDispatcher()
    deliv_reg.register_routes(deliv_disp)

    rl_env = EventEnvelope(
        id="evt_out_rl",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_out_rl",
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": ["out_rl"],
        },
    )
    assert await deliv_disp.dispatch_envelope(rl_env) == ConsumerAction.NACK

    term_env = EventEnvelope(
        id="evt_out_term",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_out_term",
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": ["out_term"],
        },
    )
    assert await deliv_disp.dispatch_envelope(term_env) == ConsumerAction.DLQ

    fetch_retry_env = EventEnvelope(
        id="evt_fetch_retry",
        source="ip.data_plane",
        event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_fetch_retry",
        payload={
            "connection_id": "conn_01",
            "stream": "orders",
            "record_ids": ["ORD-99"],
        },
    )
    assert await deliv_disp.dispatch_envelope(fetch_retry_env) == ConsumerAction.NACK


@pytest.mark.asyncio
async def test_ip_outbox_routers_route_processing_lanes_to_matching_publishers() -> None:
    orch_rt = FakeOutboxPublisher()
    orch_bulk = FakeOutboxPublisher()
    deliv_rt = FakeOutboxPublisher()
    deliv_bulk = FakeOutboxPublisher()
    notif_pub = FakeOutboxPublisher()
    events_pub = FakeOutboxPublisher()

    cp_router = build_ip_cp_outbox_router(
        orchestrator_realtime_publisher=orch_rt,
        orchestrator_bulk_publisher=orch_bulk,
        delivery_realtime_publisher=deliv_rt,
        delivery_bulk_publisher=deliv_bulk,
        notification_publisher=notif_pub,
        events_topic_publisher=events_pub,
    )
    dp_router = build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=orch_rt,
        orchestrator_bulk_publisher=orch_bulk,
        delivery_realtime_publisher=deliv_rt,
        delivery_bulk_publisher=deliv_bulk,
        notification_publisher=notif_pub,
        events_topic_publisher=events_pub,
    )

    rt_inb = EventEnvelope(
        id="e1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k1",
        payload={},
        lane=EventProcessingLane.REALTIME,
    )
    bulk_inb = EventEnvelope(
        id="e2",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k2",
        payload={},
        lane=EventProcessingLane.BULK,
    )
    rt_out = EventEnvelope(
        id="e3",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k3",
        payload={},
        lane=EventProcessingLane.REALTIME,
    )
    bulk_out = EventEnvelope(
        id="e4",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k4",
        payload={},
        lane=EventProcessingLane.BULK,
    )

    acked = await dp_router.publish_batch([rt_inb, bulk_inb, rt_out, bulk_out])
    assert sorted(acked) == ["e1", "e2", "e3", "e4"]
    assert [e.id for e in orch_rt.published] == ["e1"]
    assert [e.id for e in orch_bulk.published] == ["e2"]
    assert [e.id for e in deliv_rt.published] == ["e3"]
    assert [e.id for e in deliv_bulk.published] == ["e4"]

    sync_evt = EventEnvelope(
        id="e5",
        source="ip.control_plane",
        event_type=IpEventType.SYNC_RUN_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="k5",
        payload={},
        lane=EventProcessingLane.BULK,
    )
    await cp_router.publish(sync_evt)
    assert [e.id for e in deliv_bulk.published] == ["e4", "e5"]


def test_unified_worker_registry_resolves_all_four_ip_workers() -> None:
    assert isinstance(get_worker_instance("ip-orchestrator-worker"), IpOrchestratorWorkerModule)
    assert isinstance(get_worker_instance("ip-delivery-worker"), IpDeliveryWorkerModule)
    assert isinstance(get_worker_instance("ip-cp-jobs-worker"), IpCpJobsWorkerModule)
    assert isinstance(get_worker_instance("ip-dp-jobs-worker"), IpDpJobsWorkerModule)


@pytest.mark.asyncio
async def test_cp_jobs_worker_executes_scheduled_sweeper_with_cleanup() -> None:
    fake_repo = FakeOutboxRepository(
        initial_events=[
            EventEnvelope(
                id="evt_stuck_1",
                source="ip.data_plane",
                event_type=IpEventType.INBOUND_RECORD_CREATED.value,
                tenant_id="t_01",
                idempotency_key="idem_stuck_1",
                payload={},
            )
        ]
    )
    fake_pub = FakeOutboxPublisher()
    settings = IpEngineSettings(
        ip_control_plane_jobs_queue_url="",
        ip_data_plane_jobs_queue_url="",
    )

    cp_worker = IpCpJobsWorkerModule(publisher=fake_pub, settings=settings)
    cp_worker.cp_sweeper = OutboxSweeperUseCase(
        repository=fake_repo,
        publisher=fake_pub,
        max_concurrent_events=10,
    )
    cp_worker.cp_cleaner = OutboxCleanerUseCase(
        repository=fake_repo,
        retention_days=7,
    )
    cp_worker._wire_jobs_consumer(settings)
    assert cp_worker.job_dispatcher is not None

    await cp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value}
    )
    assert len(fake_pub.published) == 1
    assert fake_repo.completed_batches == [["evt_stuck_1"]]

    await cp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_CONTROL_PLANE_OUTBOX_CLEANUP.value}
    )
    assert fake_repo.cleaned_retention_days == [7]
    await cp_worker.stop()


@pytest.mark.asyncio
async def test_dp_jobs_worker_executes_scheduled_sweeper_with_retention_cleanup() -> None:
    fake_repo = FakeOutboxRepository()
    fake_pub = FakeOutboxPublisher()
    fake_trace_ret = FakeTraceRetentionRepository()
    settings = IpEngineSettings(
        ip_control_plane_jobs_queue_url="",
        ip_data_plane_jobs_queue_url="",
    )

    dp_worker = IpDpJobsWorkerModule(publisher=fake_pub, settings=settings)
    dp_worker.dp_sweeper = OutboxSweeperUseCase(
        repository=fake_repo,
        publisher=fake_pub,
        max_concurrent_events=10,
    )
    dp_worker.dp_cleaner = OutboxCleanerUseCase(
        repository=fake_repo,
        retention_days=7,
    )
    dp_worker.trace_retention_use_case = CleanTraceRetentionUseCase(
        repository=fake_trace_ret,
    )
    dp_worker._wire_jobs_consumer(settings, retention_days=14)
    assert dp_worker.job_dispatcher is not None

    await dp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value}
    )
    await dp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_DATA_PLANE_OUTBOX_CLEANUP.value}
    )
    await dp_worker.job_dispatcher.dispatch({"job_name": IpJobName.IP_DATA_RETENTION_CLEANUP.value})
    assert len(fake_trace_ret.trace_retention_days) == 1
    assert fake_trace_ret.processed_retention_days == [14]
    await dp_worker.stop()


@pytest.mark.asyncio
async def test_multi_shard_stitch_tick_loop_manages_background_lifecycle() -> None:
    tick_exec = FakeStitchTickExecutor()
    loop = IpMultiShardStitchTickLoop(
        tick_executor=tick_exec,
        worker_id="ip-orchestrator-test",
        free_slots=10,
        interval_seconds=0.05,
    )
    assert loop.background_tasks() == []

    dto = await loop.run_single_tick()
    assert dto is not None
    assert dto.completed_step_ids == ("step_01",)

    loop.start()
    assert loop.is_running is True
    assert len(loop.background_tasks()) == 1
    await asyncio.sleep(0.08)
    await loop.stop()
    assert loop.is_running is False
    assert loop.background_tasks() == []
    assert len(tick_exec.commands) >= 2
