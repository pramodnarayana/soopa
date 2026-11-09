"""Inbound HTTP router for the High-Frequency Interval Streams Data Plane."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_columnar_batch_processor,
    get_interval_rollup_repository,
    get_ip_control_plane_uow,
    get_ip_data_plane_uow_provider,
    get_tiered_storage,
    require_canonical_records_read,
    require_flows_write,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.interval_streams_dtos import (
    BatchManifestSummaryHttpDTO,
    BatchReconciliationOverviewHttpResponse,
    DailyTouRollupHttpDTO,
    FeederOutageClusterHttpDTO,
    IntervalBatchIngressHttpResponse,
    IntervalBatchProcessHttpResponse,
    IntervalLineageHttpDTO,
    IntervalLineageTraceHttpResponse,
    IntervalWindowCompletenessHttpDTO,
    RecordSettlementReceiptHttpRequest,
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
    ProcessIntervalBatchCommand,
    ProcessIntervalBatchUseCase,
)
from ip.engine.domain.intervals.enums import (
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.ports.outbound.columnar_batch_processor_port import ColumnarBatchProcessorPort
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)

MAX_INGRESS_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB ingress payload limit


async def _read_request_body_with_limit(
    request: Request,
    max_bytes: int = MAX_INGRESS_PAYLOAD_BYTES,
) -> bytes:
    """Reads the request stream enforcing an absolute byte limit to avoid unbounded buffering."""
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Payload exceeds maximum allowed size of {max_bytes} bytes.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/intervals",
    tags=["Integration Platform - High-Frequency Interval Streams"],
)


@router.post(
    "/ingress/{connection_id}",
    response_model=IntervalBatchIngressHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_interval_batch(
    tenant_id: str,
    connection_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    stream_name: Annotated[
        str,
        Query(..., alias="stream", description="Target interval stream name"),
    ] = "interval_readings",
    priority_lane: Annotated[
        PriorityLane,
        Query(description="QoS priority lane (P0_CRITICAL, P1_LIVE, P2_BULK_REPLAY)"),
    ] = PriorityLane.P1_LIVE,
    payload_format: Annotated[
        IntervalPayloadFormat,
        Query(description="Batch wire format (JSON_ARRAY, CSV, ARROW_IPC, PARQUET)"),
    ] = IntervalPayloadFormat.JSON_ARRAY,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> IntervalBatchIngressHttpResponse | Response:
    """L0/L1 Shock-Absorber endpoint buffering raw interval macro-batches in <10ms."""
    raw_bytes = await _read_request_body_with_limit(request)
    use_case = BufferRawIntervalBatchUseCase(
        cp_uow=cp_uow,
        dp_uow_provider=dp_uow_provider,
        storage=tiered_storage,
    )
    res = await use_case.execute(
        BufferRawIntervalBatchCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            payload_bytes=raw_bytes,
            payload_format=payload_format,
            priority_lane=priority_lane,
            correlation_id=correlation_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "ip_interval_batch_ingress.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "ip_interval_batch_ingress.accepted",
        tenant_id=tenant_id,
        connection_id=connection_id,
        batch_id=dto.batch_id,
        is_duplicate=dto.is_duplicate,
    )
    return IntervalBatchIngressHttpResponse(
        batch_id=dto.batch_id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        status=dto.status.value,
        priority_lane=dto.priority_lane.value,
        l1_raw_uri=dto.l1_raw_uri,
        payload_sha256=dto.payload_sha256,
        payload_size_bytes=dto.payload_size_bytes,
        raw_ingested_count=dto.raw_ingested_count,
        window_start_utc=dto.window_start_utc,
        window_end_utc=dto.window_end_utc,
        trace_id=dto.trace_id,
        is_duplicate=dto.is_duplicate,
    )


@router.post(
    "/batches/{batch_id}/process",
    response_model=IntervalBatchProcessHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def process_interval_batch(
    tenant_id: str,
    batch_id: str,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    columnar_processor: Annotated[
        ColumnarBatchProcessorPort, Depends(get_columnar_batch_processor)
    ],
    rollup_repo: Annotated[IntervalRollupRepositoryPort, Depends(get_interval_rollup_repository)],
    delivery_receipt_id: Annotated[str | None, Query()] = None,
) -> IntervalBatchProcessHttpResponse | Response:
    """Executes vectorized L2/L3 normalization, zero-copy Arrow IPC commit, and storm promotion."""
    use_case = ProcessIntervalBatchUseCase(
        dp_uow_provider=dp_uow_provider,
        storage=tiered_storage,
        columnar_processor=columnar_processor,
        rollup_repository=rollup_repo,
    )
    res = await use_case.execute(
        ProcessIntervalBatchCommand(
            tenant_id=tenant_id,
            batch_id=batch_id,
            delivery_receipt_id=delivery_receipt_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "ip_interval_batch_process.failed",
            tenant_id=tenant_id,
            batch_id=batch_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "ip_interval_batch_process.completed",
        tenant_id=tenant_id,
        batch_id=dto.batch_id,
        status=dto.status.value,
    )
    return IntervalBatchProcessHttpResponse(
        batch_id=dto.batch_id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        status=dto.status.value,
        raw_ingested=dto.counts.raw_ingested,
        duplicates_dropped=dto.counts.duplicates_dropped,
        valid_canonical=dto.counts.valid_canonical,
        quarantined_held=dto.counts.quarantined_held,
        is_zero_loss_balanced=dto.counts.is_balanced(),
        promoted_outage_clusters=[
            FeederOutageClusterHttpDTO(
                cluster_id=c.cluster_id,
                feeder_id=c.feeder_id,
                substation_id=c.substation_id,
                outage_meter_count=c.outage_meter_count,
                affected_meter_ids=list(c.affected_meter_ids),
                outage_start_utc=c.outage_start_utc,
                trace_id=c.trace_id,
            )
            for c in dto.promoted_outage_clusters
        ],
        l2_replica_uri=dto.l2_replica_uri,
        l3_canonical_uri=dto.l3_canonical_uri,
        trace_id=dto.trace_id,
        is_already_processed=dto.is_already_processed,
    )


@router.post(
    "/batches/{batch_id}/receipt",
    response_model=BatchManifestSummaryHttpDTO,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def record_batch_delivery_receipt(
    tenant_id: str,
    batch_id: str,
    body: RecordSettlementReceiptHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    rollup_repo: Annotated[IntervalRollupRepositoryPort, Depends(get_interval_rollup_repository)],
) -> BatchManifestSummaryHttpDTO | Response:
    """Records a downstream settlement receipt ID (e.g. billing / settlement batch acknowledgement)."""
    use_case = RecordSettlementReceiptUseCase(
        dp_uow_provider=dp_uow_provider,
        rollup_repository=rollup_repo,
    )
    res = await use_case.execute(
        RecordSettlementReceiptCommand(
            tenant_id=tenant_id,
            batch_id=batch_id,
            delivery_receipt_id=body.delivery_receipt_id,
        )
    )
    if res.is_err:
        return from_ip_error(res.unwrap_err())

    m = res.unwrap()
    return BatchManifestSummaryHttpDTO(
        batch_id=m.id,
        connection_id=m.connection_id,
        stream_name=m.stream_name,
        priority_lane=m.priority_lane.value,
        status=m.status.value,
        l1_raw_uri=m.l1_raw_uri,
        l2_replica_uri=m.l2_replica_uri,
        l3_canonical_uri=m.l3_canonical_uri,
        payload_sha256=m.payload_sha256,
        raw_ingested_count=m.raw_ingested_count,
        duplicates_dropped_count=m.duplicates_dropped_count,
        valid_canonical_count=m.valid_canonical_count,
        quarantined_held_count=m.quarantined_held_count,
        promoted_outage_clusters_count=m.promoted_outage_clusters_count,
        delivery_receipt_id=m.delivery_receipt_id,
        trace_id=m.trace_id,
        created_at=m.created_at,
        completed_at=m.completed_at,
    )


@router.get(
    "/reconciliation",
    response_model=BatchReconciliationOverviewHttpResponse,
)
async def get_interval_reconciliation(
    tenant_id: str,
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    connection_id: Annotated[str | None, Query()] = None,
    recent_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BatchReconciliationOverviewHttpResponse | Response:
    """Returns the Command Center Zero-Missing-Data Guarantee reconciliation summary."""
    use_case = GetBatchReconciliationSummaryUseCase(dp_uow_provider=dp_uow_provider)
    res = await use_case.execute(
        GetBatchReconciliationSummaryQuery(
            tenant_id=tenant_id,
            connection_id=connection_id,
            recent_limit=recent_limit,
        )
    )
    if res.is_err:
        return from_ip_error(res.unwrap_err())

    overview = res.unwrap()
    s = overview.summary
    return BatchReconciliationOverviewHttpResponse(
        tenant_id=s.tenant_id,
        connection_id=s.connection_id,
        total_batches=s.total_batches,
        completed_batches=s.completed_batches,
        in_flight_batches=s.in_flight_batches,
        failed_batches=s.failed_batches,
        raw_ingested_total=s.raw_ingested_total,
        duplicates_dropped_total=s.duplicates_dropped_total,
        valid_canonical_total=s.valid_canonical_total,
        quarantined_held_total=s.quarantined_held_total,
        in_flight_readings_total=s.in_flight_readings_total,
        is_zero_loss_balanced=s.is_zero_loss_balanced,
        recent_batches=[
            BatchManifestSummaryHttpDTO(
                batch_id=m.id,
                connection_id=m.connection_id,
                stream_name=m.stream_name,
                priority_lane=m.priority_lane.value,
                status=m.status.value,
                l1_raw_uri=m.l1_raw_uri,
                l2_replica_uri=m.l2_replica_uri,
                l3_canonical_uri=m.l3_canonical_uri,
                payload_sha256=m.payload_sha256,
                raw_ingested_count=m.raw_ingested_count,
                duplicates_dropped_count=m.duplicates_dropped_count,
                valid_canonical_count=m.valid_canonical_count,
                quarantined_held_count=m.quarantined_held_count,
                promoted_outage_clusters_count=m.promoted_outage_clusters_count,
                delivery_receipt_id=m.delivery_receipt_id,
                trace_id=m.trace_id,
                created_at=m.created_at,
                completed_at=m.completed_at,
            )
            for m in overview.recent_batches
        ],
    )


@router.get(
    "/completeness/{connection_id}",
    response_model=list[IntervalWindowCompletenessHttpDTO],
)
async def get_daily_completeness(
    tenant_id: str,
    connection_id: str,
    service_date: Annotated[date, Query(description="Service date (YYYY-MM-DD)")],
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    rollup_repo: Annotated[IntervalRollupRepositoryPort, Depends(get_interval_rollup_repository)],
    stream_name: Annotated[str | None, Query(alias="stream")] = None,
) -> list[IntervalWindowCompletenessHttpDTO] | Response:
    """Queries the pre-aggregated 96-slot daily completeness Materialized View (<25ms SLA)."""
    use_case = GetDailyCompletenessUseCase(rollup_repository=rollup_repo)
    res = await use_case.execute(
        GetDailyCompletenessQuery(
            tenant_id=tenant_id,
            connection_id=connection_id,
            service_date=service_date,
            stream_name=stream_name,
        )
    )
    if res.is_err:
        return from_ip_error(res.unwrap_err())

    return [
        IntervalWindowCompletenessHttpDTO(
            tenant_id=c.tenant_id,
            connection_id=c.connection_id,
            stream_name=c.stream_name,
            service_date=c.service_date,
            feeder_id=c.feeder_id,
            expected_intervals_per_meter=c.expected_intervals_per_meter,
            active_meter_count=c.active_meter_count,
            expected_intervals_total=c.expected_intervals_total,
            received_intervals_total=c.received_intervals_total,
            valid_intervals_total=c.valid_intervals_total,
            quarantined_intervals_total=c.quarantined_intervals_total,
            completeness_percentage=c.completeness_percentage,
        )
        for c in res.unwrap()
    ]


@router.get(
    "/tou-rollups",
    response_model=list[DailyTouRollupHttpDTO],
)
async def get_daily_tou_rollups(
    tenant_id: str,
    service_date: Annotated[date, Query(description="Service date (YYYY-MM-DD)")],
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    rollup_repo: Annotated[IntervalRollupRepositoryPort, Depends(get_interval_rollup_repository)],
    connection_id: Annotated[str | None, Query()] = None,
    feeder_id: Annotated[str | None, Query()] = None,
    source_meter_id: Annotated[str | None, Query()] = None,
) -> list[DailyTouRollupHttpDTO] | Response:
    """Queries the pre-aggregated Daily Time-of-Use (TOU) Peak/Shoulder/Off-Peak billing rollups."""
    use_case = GetDailyTouRollupsUseCase(rollup_repository=rollup_repo)
    res = await use_case.execute(
        GetDailyTouRollupsQuery(
            tenant_id=tenant_id,
            service_date=service_date,
            connection_id=connection_id,
            feeder_id=feeder_id,
            source_meter_id=source_meter_id,
        )
    )
    if res.is_err:
        return from_ip_error(res.unwrap_err())

    return [
        DailyTouRollupHttpDTO(
            tenant_id=r.tenant_id,
            gem_device_id=r.gem_device_id,
            source_meter_id=r.source_meter_id,
            service_date=r.service_date,
            feeder_id=r.feeder_id,
            kwh_peak=str(r.kwh_peak),
            kwh_shoulder=str(r.kwh_shoulder),
            kwh_off_peak=str(r.kwh_off_peak),
            kwh_net_export=str(r.kwh_net_export),
            max_kw_demand=str(r.max_kw_demand),
            valid_intervals=r.valid_intervals,
            quarantined_intervals=r.quarantined_intervals,
            latest_batch_id=r.latest_batch_id,
            connection_id=r.connection_id,
            delivery_receipt_id=r.delivery_receipt_id,
        )
        for r in res.unwrap()
    ]


@router.get(
    "/devices/{source_meter_id}/trace",
    response_model=IntervalLineageTraceHttpResponse,
)
async def trace_device_intervals(
    tenant_id: str,
    source_meter_id: str,
    service_date: Annotated[date, Query(description="Service date (YYYY-MM-DD)")],
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    rollup_repo: Annotated[IntervalRollupRepositoryPort, Depends(get_interval_rollup_repository)],
) -> IntervalLineageTraceHttpResponse | Response:
    """Executes Two-Tier Trace Linkage joining a device's 96-slot load curve to L1-L5 batch lineage."""
    use_case = TraceIntervalLineageUseCase(
        dp_uow_provider=dp_uow_provider,
        rollup_repository=rollup_repo,
    )
    res = await use_case.execute(
        TraceIntervalLineageQuery(
            tenant_id=tenant_id,
            source_meter_id=source_meter_id,
            service_date=service_date,
        )
    )
    if res.is_err:
        return from_ip_error(res.unwrap_err())

    trace_dto = res.unwrap()
    return IntervalLineageTraceHttpResponse(
        tenant_id=trace_dto.tenant_id,
        source_meter_id=trace_dto.source_meter_id,
        service_date=trace_dto.service_date,
        total_intervals=trace_dto.total_intervals,
        valid_intervals=trace_dto.valid_intervals,
        quarantined_intervals=trace_dto.quarantined_intervals,
        intervals=[
            IntervalLineageHttpDTO(
                interval_end_utc=item.reading.interval_end_utc,
                gem_device_id=item.reading.gem_device_id,
                source_meter_id=item.reading.source_meter_id,
                endpoint_location_id=item.reading.endpoint_location_id,
                feeder_id=item.reading.feeder_id,
                substation_id=item.reading.substation_id,
                tariff_bucket=item.reading.tariff_bucket.value,
                quality_status=item.reading.quality_status.value,
                scaled_kwh_delivered=str(item.reading.scaled_kwh_delivered),
                scaled_kwh_received=str(item.reading.scaled_kwh_received),
                reactive_kvarh=str(item.reading.reactive_kvarh),
                voltage_v=item.reading.voltage_v,
                quarantine_reason=item.reading.quarantine_reason,
                source_batch_id=item.batch_id,
                parquet_row_offset=item.reading.parquet_row_offset,
                batch_status=item.batch_status.value,
                priority_lane=item.priority_lane.value,
                l1_raw_uri=item.l1_raw_uri,
                l2_replica_uri=item.l2_replica_uri,
                l3_canonical_uri=item.l3_canonical_uri,
                payload_sha256=item.payload_sha256,
                delivery_receipt_id=item.delivery_receipt_id,
                trace_id=item.trace_id,
            )
            for item in trace_dto.intervals
        ],
    )


__all__ = ["router"]
