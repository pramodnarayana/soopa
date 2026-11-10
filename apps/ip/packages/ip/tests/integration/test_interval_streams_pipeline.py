"""Narrow Integration Tests for the High-Frequency Interval Streams Pipeline against real PostgreSQL."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.inbound.workers.ip_orchestrator_route_registry import (
    IpOrchestratorRouteRegistry,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    BatchManifestModel,
    IpDataPlaneOutboxRecord,
)
from ip.engine.adapters.outbound.intervals import (
    ColumnarIntervalRollupRepositoryAdapter,
    VectorizedIntervalBatchNormalizerAdapter,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    TieredStorageAdapter,
)
from ip.engine.application.use_cases.intervals.buffer_raw_interval_batch_use_case import (
    BufferRawIntervalBatchCommand,
    BufferRawIntervalBatchUseCase,
)
from ip.engine.application.use_cases.intervals.interval_rollup_use_cases import (
    GetBatchReconciliationSummaryQuery,
    GetBatchReconciliationSummaryUseCase,
    GetDailyCompletenessQuery,
    GetDailyCompletenessUseCase,
    GetDailyTouRollupsQuery,
    GetDailyTouRollupsUseCase,
    RecordSettlementReceiptCommand,
    RecordSettlementReceiptUseCase,
    TraceIntervalLineageQuery,
    TraceIntervalLineageUseCase,
)
from ip.engine.application.use_cases.intervals.process_interval_batch_use_case import (
    ProcessIntervalBatchUseCase,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.worker_ports import (
    IpBackfillStreamNormalizationExecutorPort,
    IpNormalizeReplicaExecutorPort,
)
from ip.engine.bootstrap.container import (
    create_ip_control_plane_uow,
    create_ip_tenant_resolver,
    create_ip_tenant_uow_provider,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.enums import IpEventType, IpOutboxSource
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    CimQualityStatus,
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.domain.intervals.models import StormAggregationPolicy
from ip.engine.domain.normalization.enums import NormalizationOutcome
from pubsub.enums import ConsumerAction
from seedwork.events import EventEnvelope
from sqlalchemy import select
from storage.ports.payload_storage_port import PayloadStoragePort

pytestmark = pytest.mark.integration


class _InMemoryPayloadStorage(PayloadStoragePort):
    """In-memory PayloadStoragePort for deterministic narrow integration testing."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def upload(
        self,
        tenant_id: str,
        message_id: str,
        payload: bytes,
    ) -> str:
        s3_key = f"s3://ip-test-bucket/{tenant_id}/{message_id}"
        self.blobs[s3_key] = payload
        return s3_key

    async def download(self, s3_key: str) -> bytes | None:
        return self.blobs.get(s3_key)

    async def delete(self, s3_key: str) -> bool:
        return self.blobs.pop(s3_key, None) is not None

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        return f"https://ip-test-bucket.s3.amazonaws.com/{storage_uri}?exp={expiry_seconds}"


class _NoOpNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=NormalizationOutcome.SKIPPED_STALE,
            )
        )


class _NoOpBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        return Result.ok(
            BackfillStreamNormalizationResultDTO(
                processed_count=0,
                normalized_count=0,
                rejected_count=0,
                tombstoned_count=0,
                skipped_count=0,
                chunks_processed=0,
            )
        )


async def _seed_interval_connection(
    global_session: GlobalSession,
    tenant_id: str,
) -> Connection:
    cp_uow = create_ip_control_plane_uow(global_session)
    conn = Connection.create(
        tenant_id=tenant_id,
        app_id="grid_headend_source",
        name="Primary Grid Interval Source",
        auth_type=AuthType.API_KEY,
        public_config={"region": "ERCOT-NORTH"},
        encrypted_credentials=b"encrypted",
        endpoint_for_fingerprint="https://grid-headend.example.com/v1/intervals",
    )
    conn.activate()
    await cp_uow.connections.save(conn)
    await cp_uow.commit()
    return conn


@pytest.mark.asyncio
async def test_interval_batch_ingress_persists_manifest_with_claim_check_event(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    conn = await _seed_interval_connection(global_session, seeded_ip_tenant)
    storage = TieredStorageAdapter(storage_client=_InMemoryPayloadStorage(), threshold_bytes=10)
    resolver = create_ip_tenant_resolver(transactional_router)
    dp_uow_provider = create_ip_tenant_uow_provider(
        resolver=resolver,
        db_router=transactional_router,
        storage=storage,
    )
    cp_uow = create_ip_control_plane_uow(global_session)

    readings = [
        {
            "source_meter_id": "DEV_INGRESS_01",
            "feeder_id": "FDR_101",
            "substation_id": "SUB_10",
            "interval_end_utc": datetime(2026, 11, 9, 10, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "1.7500",
            "voltage_v": 240.2,
        },
        {
            "source_meter_id": "DEV_INGRESS_02",
            "feeder_id": "FDR_101",
            "substation_id": "SUB_10",
            "interval_end_utc": datetime(2026, 11, 9, 10, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "2.1000",
            "voltage_v": 239.9,
        },
    ]
    payload_bytes = json.dumps(readings).encode("utf-8")

    buffer_uc = BufferRawIntervalBatchUseCase(
        cp_uow=cp_uow,
        dp_uow_provider=dp_uow_provider,
        storage=storage,
    )
    res1 = await buffer_uc.execute(
        BufferRawIntervalBatchCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="interval_readings_15m",
            payload_bytes=payload_bytes,
            payload_format=IntervalPayloadFormat.JSON_ARRAY,
            priority_lane=PriorityLane.P2_BULK_REPLAY,
            correlation_id="corr_interval_001",
        )
    )
    assert res1.is_ok is True
    dto1 = res1.unwrap()
    assert dto1.is_duplicate is False
    assert dto1.raw_ingested_count == 2
    assert dto1.status is BatchManifestStatus.INGESTED
    assert dto1.l1_raw_uri.startswith("s3://")

    # Verify PostgreSQL persistence in ip_batch_manifests and ip_outbox (bulk lane)
    db_row = await tenant_session.get(BatchManifestModel, dto1.batch_id)
    assert db_row is not None
    assert db_row.raw_ingested_count == 2
    assert db_row.status == BatchManifestStatus.INGESTED.value

    outbox_rows = (
        (
            await tenant_session.execute(
                select(IpDataPlaneOutboxRecord).where(
                    IpDataPlaneOutboxRecord.tenant_id == seeded_ip_tenant,
                    IpDataPlaneOutboxRecord.event_type == IpEventType.INTERVAL_BATCH_INGESTED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox_rows) == 1
    assert outbox_rows[0].lane == "bulk"

    # Re-submitting identical payload bytes returns idempotent duplicate response
    res2 = await buffer_uc.execute(
        BufferRawIntervalBatchCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="interval_readings_15m",
            payload_bytes=payload_bytes,
            payload_format=IntervalPayloadFormat.JSON_ARRAY,
            priority_lane=PriorityLane.P2_BULK_REPLAY,
        )
    )
    assert res2.is_ok is True
    dto2 = res2.unwrap()
    assert dto2.is_duplicate is True
    assert dto2.batch_id == dto1.batch_id


@pytest.mark.asyncio
async def test_interval_orchestrator_processes_batch_end_to_end_pipeline(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    conn = await _seed_interval_connection(global_session, seeded_ip_tenant)
    storage = TieredStorageAdapter(storage_client=_InMemoryPayloadStorage(), threshold_bytes=10)
    resolver = create_ip_tenant_resolver(transactional_router)
    dp_uow_provider = create_ip_tenant_uow_provider(
        resolver=resolver,
        db_router=transactional_router,
        storage=storage,
    )
    cp_uow = create_ip_control_plane_uow(global_session)
    columnar_processor = VectorizedIntervalBatchNormalizerAdapter(
        default_storm_policy=StormAggregationPolicy(freshness_window_minutes=0)
    )
    rollup_repo = ColumnarIntervalRollupRepositoryAdapter()

    service_day = date(2026, 11, 9)
    base_ts = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    readings: list[dict[str, object]] = []
    # 5 valid readings for DEV_MAIN_01
    for i in range(5):
        readings.append(
            {
                "source_meter_id": "DEV_MAIN_01",
                "endpoint_location_id": "LOC_MAIN_01",
                "feeder_id": "FDR_MAIN_01",
                "substation_id": "SUB_MAIN_01",
                "interval_end_utc": (base_ts + timedelta(minutes=15 * i)).isoformat(),
                "kwh_delivered": "1.5000",
                "kwh_received": "0.2500",
                "voltage_v": 240.0,
            }
        )
    # 1 duplicate reading of index 0
    readings.append(dict(readings[0]))
    # 1 spike reading for DEV_MAIN_01 (> 250.0 ceiling)
    readings.append(
        {
            "source_meter_id": "DEV_MAIN_01",
            "endpoint_location_id": "LOC_MAIN_01",
            "feeder_id": "FDR_MAIN_01",
            "substation_id": "SUB_MAIN_01",
            "interval_end_utc": (base_ts + timedelta(minutes=15 * 5)).isoformat(),
            "kwh_delivered": "450.0000",
            "kwh_received": "0.0000",
            "voltage_v": 240.0,
        }
    )
    # 30 zero-voltage readings on FDR_STORM_99 (>= 25 threshold -> 1 collapsed FeederOutageCluster)
    outage_ts = datetime(2026, 11, 9, 18, 15, tzinfo=UTC).isoformat()
    for idx in range(30):
        readings.append(
            {
                "source_meter_id": f"DEV_STORM_{idx:03d}",
                "endpoint_location_id": f"LOC_STORM_{idx:03d}",
                "feeder_id": "FDR_STORM_99",
                "substation_id": "SUB_STORM_99",
                "interval_end_utc": outage_ts,
                "kwh_delivered": "0.0000",
                "voltage_v": 0.0,
            }
        )

    buffer_uc = BufferRawIntervalBatchUseCase(
        cp_uow=cp_uow,
        dp_uow_provider=dp_uow_provider,
        storage=storage,
    )
    ingested_dto = (
        await buffer_uc.execute(
            BufferRawIntervalBatchCommand(
                tenant_id=seeded_ip_tenant,
                connection_id=conn.id,
                stream_name="interval_readings_15m",
                payload_bytes=json.dumps(readings).encode("utf-8"),
                payload_format=IntervalPayloadFormat.JSON_ARRAY,
                priority_lane=PriorityLane.P1_LIVE,
            )
        )
    ).unwrap()

    process_uc = ProcessIntervalBatchUseCase(
        dp_uow_provider=dp_uow_provider,
        storage=storage,
        columnar_processor=columnar_processor,
        rollup_repository=rollup_repo,
    )
    route_registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        normalize_use_case=_NoOpNormalizeExecutor(),
        backfill_use_case=_NoOpBackfillExecutor(),
        process_interval_batch_use_case=process_uc,
    )

    envelope = EventEnvelope(
        id="evt_ibatch_001",
        event_type=IpEventType.INTERVAL_BATCH_INGESTED.value,
        source=IpOutboxSource.DATA_PLANE.value,
        tenant_id=seeded_ip_tenant,
        idempotency_key=f"idem_ibatch_{ingested_dto.batch_id}",
        trace_id=ingested_dto.trace_id,
        payload={
            "tenant_id": seeded_ip_tenant,
            "batch_id": ingested_dto.batch_id,
            "connection_id": conn.id,
            "stream_name": "interval_readings_15m",
            "l1_raw_uri": ingested_dto.l1_raw_uri,
            "priority_lane": PriorityLane.P1_LIVE.value,
            "trace_id": ingested_dto.trace_id,
        },
    )
    action = await route_registry.handle_interval_batch_ingested(envelope)
    assert action is ConsumerAction.ACK

    # Verify storm-promoted FeederOutageClusterDetectedEvent is staged on the P0_CRITICAL realtime lane
    outage_outbox_rows = (
        (
            await tenant_session.execute(
                select(IpDataPlaneOutboxRecord).where(
                    IpDataPlaneOutboxRecord.tenant_id == seeded_ip_tenant,
                    IpDataPlaneOutboxRecord.event_type == IpEventType.FEEDER_OUTAGE_DETECTED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outage_outbox_rows) == 1
    assert outage_outbox_rows[0].lane == "realtime"
    assert outage_outbox_rows[0].payload["feeder_id"] == "FDR_STORM_99"
    assert outage_outbox_rows[0].payload["outage_meter_count"] == 30

    # Record downstream settlement receipt
    receipt_uc = RecordSettlementReceiptUseCase(
        dp_uow_provider=dp_uow_provider,
        rollup_repository=rollup_repo,
    )
    receipt_res = await receipt_uc.execute(
        RecordSettlementReceiptCommand(
            tenant_id=seeded_ip_tenant,
            batch_id=ingested_dto.batch_id,
            delivery_receipt_id="SETTLEMENT-RECEIPT-2026-001",
        )
    )
    assert receipt_res.is_ok is True
    assert receipt_res.unwrap().delivery_receipt_id == "SETTLEMENT-RECEIPT-2026-001"

    # Verify Zero-Loss Reconciliation Summary
    recon_uc = GetBatchReconciliationSummaryUseCase(dp_uow_provider=dp_uow_provider)
    recon_overview = (
        await recon_uc.execute(
            GetBatchReconciliationSummaryQuery(
                tenant_id=seeded_ip_tenant,
                connection_id=conn.id,
            )
        )
    ).unwrap()
    assert recon_overview.summary.total_batches == 1
    assert recon_overview.summary.completed_batches == 1
    assert recon_overview.summary.raw_ingested_total == 37
    assert recon_overview.summary.duplicates_dropped_total == 1
    assert recon_overview.summary.valid_canonical_total == 35
    assert recon_overview.summary.quarantined_held_total == 1
    assert recon_overview.summary.is_zero_loss_balanced is True

    # Verify Daily Completeness Materialized View
    comp_uc = GetDailyCompletenessUseCase(rollup_repository=rollup_repo)
    comp_rows = (
        await comp_uc.execute(
            GetDailyCompletenessQuery(
                tenant_id=seeded_ip_tenant,
                connection_id=conn.id,
                service_date=service_day,
            )
        )
    ).unwrap()
    assert len(comp_rows) == 2
    main_feeder_comp = next(c for c in comp_rows if c.feeder_id == "FDR_MAIN_01")
    assert main_feeder_comp.valid_intervals_total == 5
    assert main_feeder_comp.quarantined_intervals_total == 1

    # Verify Daily TOU Rollups Materialized View
    tou_uc = GetDailyTouRollupsUseCase(rollup_repository=rollup_repo)
    tou_rows = (
        await tou_uc.execute(
            GetDailyTouRollupsQuery(
                tenant_id=seeded_ip_tenant,
                service_date=service_day,
                source_meter_id="DEV_MAIN_01",
            )
        )
    ).unwrap()
    assert len(tou_rows) == 1
    assert tou_rows[0].kwh_shoulder == Decimal("7.5000")
    assert tou_rows[0].kwh_net_export == Decimal("1.2500")
    assert tou_rows[0].valid_intervals == 5
    assert tou_rows[0].quarantined_intervals == 1
    assert tou_rows[0].delivery_receipt_id == "SETTLEMENT-RECEIPT-2026-001"

    # Verify Two-Tier Trace Linkage joining 15-min intervals to macro-batch L1-L5 lineage
    trace_uc = TraceIntervalLineageUseCase(
        dp_uow_provider=dp_uow_provider,
        rollup_repository=rollup_repo,
    )
    trace_dto = (
        await trace_uc.execute(
            TraceIntervalLineageQuery(
                tenant_id=seeded_ip_tenant,
                source_meter_id="DEV_MAIN_01",
                service_date=service_day,
            )
        )
    ).unwrap()
    assert trace_dto.total_intervals == 6
    assert trace_dto.valid_intervals == 5
    assert trace_dto.quarantined_intervals == 1
    spike_lineage = next(
        item
        for item in trace_dto.intervals
        if item.reading.quality_status is CimQualityStatus.QUARANTINED_SPIKE
    )
    assert spike_lineage.batch_id == ingested_dto.batch_id
    assert spike_lineage.l1_raw_uri == ingested_dto.l1_raw_uri
    assert spike_lineage.l2_replica_uri is not None
    assert spike_lineage.l3_canonical_uri is not None
    assert spike_lineage.delivery_receipt_id == "SETTLEMENT-RECEIPT-2026-001"
