"""Reconciliation, TOU rollup, completeness, and Two-Tier Trace Linkage use cases for Interval Streams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import structlog

from ip.engine.domain.exceptions import (
    IntervalBatchNotFoundError,
    IpError,
    Result,
)
from ip.engine.domain.intervals.enums import CimQualityStatus
from ip.engine.domain.intervals.models import (
    BatchManifest,
    BatchReconciliationSummary,
    DailyTouBillingRollup,
    IntervalLineageTrace,
    IntervalWindowCompleteness,
)
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GetBatchReconciliationSummaryQuery:
    """Query for the Command Center Zero-Missing-Data Guarantee Bar."""

    tenant_id: str
    connection_id: str | None = None
    recent_limit: int = 20


@dataclass(frozen=True, slots=True)
class BatchReconciliationOverviewResponse:
    """Response combining aggregate Zero-Loss counters and recent BatchManifests."""

    summary: BatchReconciliationSummary
    recent_batches: tuple[BatchManifest, ...]


@dataclass(frozen=True, slots=True)
class GetDailyCompletenessQuery:
    """Query for the 96-slot daily interval completeness ribbon."""

    tenant_id: str
    connection_id: str
    service_date: date
    stream_name: str | None = None


@dataclass(frozen=True, slots=True)
class GetDailyTouRollupsQuery:
    """Query for Daily Time-of-Use (TOU) Peak/Shoulder/Off-Peak billing rollups."""

    tenant_id: str
    service_date: date
    feeder_id: str | None = None
    source_meter_id: str | None = None


@dataclass(frozen=True, slots=True)
class TraceIntervalLineageQuery:
    """Query for Two-Tier Trace Linkage: 96-slot device load curve + macro-batch L1-L5 lineage."""

    tenant_id: str
    source_meter_id: str
    service_date: date


@dataclass(frozen=True, slots=True)
class TraceIntervalLineageResponse:
    """Two-Tier Trace Linkage response for a device's daily interval load curve."""

    tenant_id: str
    source_meter_id: str
    service_date: date
    total_intervals: int
    valid_intervals: int
    quarantined_intervals: int
    intervals: tuple[IntervalLineageTrace, ...]


@dataclass(frozen=True, slots=True)
class RecordSettlementReceiptCommand:
    """Command to record a downstream settlement receipt ID (e.g. CIS / billing receipt) on a batch."""

    tenant_id: str
    batch_id: str
    delivery_receipt_id: str


class GetBatchReconciliationSummaryUseCase:
    """Retrieves the Zero-Missing-Data Guarantee reconciliation summary and recent batch ledger."""

    def __init__(self, dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._dp_uow_provider = dp_uow_provider

    async def execute(
        self,
        query: GetBatchReconciliationSummaryQuery,
    ) -> Result[BatchReconciliationOverviewResponse, IpError]:
        shard_res = await self._dp_uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        async with self._dp_uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            summary = await uow.batch_manifests.get_reconciliation_summary(
                query.tenant_id,
                connection_id=query.connection_id,
            )
            recent = await uow.batch_manifests.list_by_connection(
                query.tenant_id,
                connection_id=query.connection_id,
                limit=query.recent_limit,
            )
        return Result.ok(
            BatchReconciliationOverviewResponse(
                summary=summary,
                recent_batches=tuple(recent),
            )
        )


class GetDailyCompletenessUseCase:
    """Queries the pre-aggregated 96-slot daily completeness Materialized View."""

    def __init__(self, rollup_repository: IntervalRollupRepositoryPort) -> None:
        self._rollup_repository = rollup_repository

    async def execute(
        self,
        query: GetDailyCompletenessQuery,
    ) -> Result[tuple[IntervalWindowCompleteness, ...], IpError]:
        return await self._rollup_repository.get_daily_completeness(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            service_date=query.service_date,
            stream_name=query.stream_name,
        )


class GetDailyTouRollupsUseCase:
    """Queries the pre-aggregated Daily Time-of-Use (TOU) billing rollup Materialized View."""

    def __init__(self, rollup_repository: IntervalRollupRepositoryPort) -> None:
        self._rollup_repository = rollup_repository

    async def execute(
        self,
        query: GetDailyTouRollupsQuery,
    ) -> Result[tuple[DailyTouBillingRollup, ...], IpError]:
        return await self._rollup_repository.get_daily_tou_rollups(
            tenant_id=query.tenant_id,
            service_date=query.service_date,
            feeder_id=query.feeder_id,
            source_meter_id=query.source_meter_id,
        )


class TraceIntervalLineageUseCase:
    """Executes Two-Tier Trace Linkage joining micro-interval bars to macro-batch L1-L5 lineage."""

    def __init__(
        self,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        rollup_repository: IntervalRollupRepositoryPort,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._rollup_repository = rollup_repository

    async def execute(
        self,
        query: TraceIntervalLineageQuery,
    ) -> Result[TraceIntervalLineageResponse, IpError]:
        curve_res = await self._rollup_repository.get_device_load_curve(
            tenant_id=query.tenant_id,
            source_meter_id=query.source_meter_id,
            service_date=query.service_date,
        )
        if curve_res.is_err:
            return Result.fail(curve_res.unwrap_err())
        readings = curve_res.unwrap()
        if not readings:
            return Result.ok(
                TraceIntervalLineageResponse(
                    tenant_id=query.tenant_id,
                    source_meter_id=query.source_meter_id,
                    service_date=query.service_date,
                    total_intervals=0,
                    valid_intervals=0,
                    quarantined_intervals=0,
                    intervals=(),
                )
            )

        shard_res = await self._dp_uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        unique_batch_ids = {r.source_batch_id for r in readings}
        manifests_by_id: dict[str, BatchManifest] = {}
        async with self._dp_uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            for b_id in unique_batch_ids:
                manifest = await uow.batch_manifests.get_by_id(b_id, query.tenant_id)
                if manifest is not None:
                    manifests_by_id[b_id] = manifest

        linked_intervals: list[IntervalLineageTrace] = []
        valid_count = 0
        quarantined_count = 0
        for reading in readings:
            if reading.quality_status is CimQualityStatus.QUARANTINED_SPIKE:
                quarantined_count += 1
            else:
                valid_count += 1
            manifest = manifests_by_id.get(reading.source_batch_id)
            if manifest is None:
                continue
            linked_intervals.append(
                IntervalLineageTrace(
                    reading=reading,
                    batch_id=manifest.id,
                    batch_status=manifest.status,
                    stream_name=manifest.stream_name,
                    priority_lane=manifest.priority_lane,
                    l1_raw_uri=manifest.l1_raw_uri,
                    l2_replica_uri=manifest.l2_replica_uri,
                    l3_canonical_uri=manifest.l3_canonical_uri,
                    payload_sha256=manifest.payload_sha256,
                    reconciliation_counts=manifest.reconciliation_counts,
                    delivery_receipt_id=reading.delivery_receipt_id or manifest.delivery_receipt_id,
                    trace_id=manifest.trace_id,
                )
            )

        return Result.ok(
            TraceIntervalLineageResponse(
                tenant_id=query.tenant_id,
                source_meter_id=query.source_meter_id,
                service_date=query.service_date,
                total_intervals=len(linked_intervals),
                valid_intervals=valid_count,
                quarantined_intervals=quarantined_count,
                intervals=tuple(linked_intervals),
            )
        )


class RecordSettlementReceiptUseCase:
    """Records a downstream settlement receipt ID across both OLTP manifest and columnar rollup store."""

    def __init__(
        self,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        rollup_repository: IntervalRollupRepositoryPort,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._rollup_repository = rollup_repository

    async def execute(
        self,
        command: RecordSettlementReceiptCommand,
    ) -> Result[BatchManifest, IpError]:
        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        async with self._dp_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            manifest = await uow.batch_manifests.get_by_id(command.batch_id, command.tenant_id)
            if manifest is None:
                return Result.fail(IntervalBatchNotFoundError.for_batch(command.batch_id))

            manifest.record_delivery_receipt(command.delivery_receipt_id)
            rollup_res = await self._rollup_repository.record_delivery_receipt(
                tenant_id=command.tenant_id,
                batch_id=command.batch_id,
                delivery_receipt_id=command.delivery_receipt_id,
            )
            if rollup_res.is_err:
                rollup_err = rollup_res.unwrap_err()
                logger.error(
                    "settlement_delivery_receipt_rollup_update_failed",
                    tenant_id=command.tenant_id,
                    batch_id=command.batch_id,
                    reason=rollup_err.message,
                )
                return Result.fail(rollup_err)
            await uow.batch_manifests.save(manifest)
            await uow.commit()

        logger.info(
            "settlement_delivery_receipt_recorded",
            tenant_id=command.tenant_id,
            batch_id=command.batch_id,
            delivery_receipt_id=command.delivery_receipt_id,
        )
        return Result.ok(manifest)


__all__ = [
    "BatchReconciliationOverviewResponse",
    "GetBatchReconciliationSummaryQuery",
    "GetBatchReconciliationSummaryUseCase",
    "GetDailyCompletenessQuery",
    "GetDailyCompletenessUseCase",
    "GetDailyTouRollupsQuery",
    "GetDailyTouRollupsUseCase",
    "RecordSettlementReceiptCommand",
    "RecordSettlementReceiptUseCase",
    "TraceIntervalLineageQuery",
    "TraceIntervalLineageResponse",
    "TraceIntervalLineageUseCase",
]
