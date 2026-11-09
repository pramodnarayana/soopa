"""Domain models, value objects, and BatchManifest aggregate for High-Frequency Interval Streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import ClassVar

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot

from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import IntervalReconciliationImbalanceError
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    CimQualityStatus,
    IntervalPayloadFormat,
    PriorityLane,
    TariffBucket,
)
from ip.engine.domain.intervals.events import (
    FeederOutageClusterDetectedEvent,
    IntervalBatchIngestedEvent,
    IntervalBatchProcessedEvent,
)
from ip.engine.domain.trace.enums import IpTraceEventType, PipelineStage, TraceEventStatus
from ip.engine.domain.trace.trace_event import IpTraceEvent


@dataclass(frozen=True, slots=True)
class BatchReconciliationCounts:
    """Immutable value object enforcing the Zero-Loss Accounting Equation for an interval batch.

    Equation: raw_ingested == duplicates_dropped + valid_canonical + quarantined_held
    """

    raw_ingested: int
    duplicates_dropped: int = 0
    valid_canonical: int = 0
    quarantined_held: int = 0

    @property
    def accounted_total(self) -> int:
        return self.duplicates_dropped + self.valid_canonical + self.quarantined_held

    def is_balanced(self) -> bool:
        return (
            self.raw_ingested >= 0
            and self.duplicates_dropped >= 0
            and self.valid_canonical >= 0
            and self.quarantined_held >= 0
            and self.raw_ingested == self.accounted_total
        )


@dataclass(frozen=True, slots=True)
class StormAggregationPolicy:
    """Storm-Safe Outage Promotion policy preventing queue floods during feeder outages.

    - Below `storm_threshold_meters`: promotes individual endpoint outage clusters.
    - At or above `storm_threshold_meters`: collapses all 0.0V endpoints on the same
      (feeder_id, substation_id) within a common time window into a single FeederOutageCluster event.
    """

    storm_threshold_meters: int = 25
    zero_voltage_threshold: float = 0.01
    time_window_minutes: int = 15
    freshness_window_minutes: int = 60


@dataclass(frozen=True, slots=True)
class VeeValidationPolicy:
    """Validation, Estimation, and Editing (VEE) policy for interval streams."""

    max_interval_kwh: Decimal = Decimal("50.0000")
    mad_spike_multiplier: Decimal = Decimal("10.0")
    expected_interval_minutes: int = 15


@dataclass(frozen=True, slots=True)
class FeederOutageCluster:
    """Immutable value object representing a detected 0.0V outage cluster on a distribution feeder."""

    cluster_id: str
    tenant_id: str
    connection_id: str
    batch_id: str
    feeder_id: str
    substation_id: str
    outage_meter_count: int
    affected_meter_ids: tuple[str, ...]
    outage_start_utc: datetime
    trace_id: str


@dataclass(frozen=True, slots=True)
class IntervalReading:
    """Canonical interval reading (15-min or 5-min) with Two-Tier Trace Linkage pointers."""

    tenant_id: str
    connection_id: str
    gem_device_id: str
    source_meter_id: str
    endpoint_location_id: str
    feeder_id: str
    substation_id: str
    tariff_bucket: TariffBucket
    quality_status: CimQualityStatus
    interval_end_utc: datetime
    scaled_kwh_delivered: Decimal
    scaled_kwh_received: Decimal
    reactive_kvarh: Decimal
    voltage_v: float
    source_batch_id: str
    parquet_row_offset: int
    trace_id: str
    updated_at_utc: datetime
    quarantine_reason: str | None = None
    delivery_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class HourlyIntervalRollup:
    """Pre-aggregated hourly interval rollup per device and tariff bucket."""

    tenant_id: str
    gem_device_id: str
    source_meter_id: str
    hour_start_utc: datetime
    feeder_id: str
    tariff_bucket: TariffBucket
    interval_count: int
    total_kwh_delivered: Decimal
    total_kwh_received: Decimal
    max_kw_demand: Decimal
    avg_voltage_v: float


@dataclass(frozen=True, slots=True)
class DailyTouBillingRollup:
    """Daily Time-of-Use (TOU) billing aggregate ready for downstream CIS/MDMS settlement."""

    tenant_id: str
    gem_device_id: str
    source_meter_id: str
    service_date: date
    feeder_id: str
    kwh_peak: Decimal
    kwh_shoulder: Decimal
    kwh_off_peak: Decimal
    kwh_net_export: Decimal
    max_kw_demand: Decimal
    valid_intervals: int
    quarantined_intervals: int
    latest_batch_id: str
    connection_id: str = ""
    delivery_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntervalWindowCompleteness:
    """96-slot daily interval completeness summary per feeder and stream."""

    tenant_id: str
    connection_id: str
    stream_name: str
    service_date: date
    feeder_id: str
    expected_intervals_per_meter: int
    active_meter_count: int
    expected_intervals_total: int
    received_intervals_total: int
    valid_intervals_total: int
    quarantined_intervals_total: int
    completeness_percentage: float


@dataclass(frozen=True, slots=True)
class BatchReconciliationSummary:
    """Zero-Missing-Data Guarantee summary across all interval macro-batches for a connection/tenant."""

    tenant_id: str
    connection_id: str | None
    total_batches: int
    completed_batches: int
    in_flight_batches: int
    failed_batches: int
    raw_ingested_total: int
    duplicates_dropped_total: int
    valid_canonical_total: int
    quarantined_held_total: int
    in_flight_readings_total: int
    is_zero_loss_balanced: bool


@dataclass(frozen=True, slots=True)
class IntervalLineageTrace:
    """Two-Tier Trace Linkage object joining a 15-min interval reading to its macro-batch L1-L5 lineage."""

    reading: IntervalReading
    batch_id: str
    batch_status: BatchManifestStatus
    stream_name: str
    priority_lane: PriorityLane
    l1_raw_uri: str
    l2_replica_uri: str | None
    l3_canonical_uri: str | None
    payload_sha256: str
    reconciliation_counts: BatchReconciliationCounts
    delivery_receipt_id: str | None
    trace_id: str


@dataclass(kw_only=True, eq=False)
class BatchManifest(TracedAggregateRoot):
    """Traced Aggregate Root for an interval macro-batch in `ip_batch_manifests`."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.INTERVAL_BATCH.value

    id: str
    connection_id: str
    app_id: str
    stream_name: str
    priority_lane: PriorityLane = PriorityLane.P1_LIVE
    payload_format: IntervalPayloadFormat = IntervalPayloadFormat.JSON_ARRAY
    status: BatchManifestStatus = BatchManifestStatus.INGESTED
    l1_raw_uri: str
    l2_replica_uri: str | None = None
    l3_canonical_uri: str | None = None
    inline_payload: JsonDict | None = None
    payload_sha256: str
    payload_size_bytes: int
    window_start_utc: datetime
    window_end_utc: datetime
    raw_ingested_count: int
    duplicates_dropped_count: int = 0
    valid_canonical_count: int = 0
    quarantined_held_count: int = 0
    promoted_outage_clusters_count: int = 0
    delivery_receipt_id: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def reconciliation_counts(self) -> BatchReconciliationCounts:
        return BatchReconciliationCounts(
            raw_ingested=self.raw_ingested_count,
            duplicates_dropped=self.duplicates_dropped_count,
            valid_canonical=self.valid_canonical_count,
            quarantined_held=self.quarantined_held_count,
        )

    @classmethod
    def create_ingested(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        stream_name: str,
        l1_raw_uri: str,
        payload_sha256: str,
        payload_size_bytes: int,
        raw_ingested_count: int,
        window_start_utc: datetime,
        window_end_utc: datetime,
        priority_lane: PriorityLane = PriorityLane.P1_LIVE,
        payload_format: IntervalPayloadFormat = IntervalPayloadFormat.JSON_ARRAY,
        inline_payload: JsonDict | None = None,
        batch_id: str | None = None,
        trace_id: str | None = None,
        correlation_id: str | None = None,
    ) -> BatchManifest:
        """Creates a new INGESTED BatchManifest and stages its L1 trace and domain events."""
        resolved_batch_id = batch_id or generate_id(cls.ID_PREFIX)
        resolved_trace_id = trace_id or generate_id(IpIdPrefix.TRACE.value)
        now = datetime.now(UTC)

        manifest = cls(
            id=resolved_batch_id,
            tenant_id=tenant_id,
            trace_id=resolved_trace_id,
            correlation_id=correlation_id,
            connection_id=connection_id,
            app_id=app_id,
            stream_name=stream_name,
            priority_lane=priority_lane,
            payload_format=payload_format,
            status=BatchManifestStatus.INGESTED,
            l1_raw_uri=l1_raw_uri,
            inline_payload=dict(inline_payload) if inline_payload is not None else None,
            payload_sha256=payload_sha256,
            payload_size_bytes=payload_size_bytes,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            raw_ingested_count=raw_ingested_count,
            created_at=now,
        )

        manifest.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.INTERVAL_BATCH_INGESTED.value,
                stage=PipelineStage.INGEST,
                status=TraceEventStatus.SUCCESS,
                summary_message=(
                    f"Buffered interval batch '{resolved_batch_id}' for stream "
                    f"'{stream_name}' ({raw_ingested_count} readings, {payload_size_bytes} bytes)."
                ),
            )
        )

        manifest.add_domain_event(
            IntervalBatchIngestedEvent(
                batch_id=resolved_batch_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                app_id=app_id,
                stream_name=stream_name,
                l1_raw_uri=l1_raw_uri,
                payload_sha256=payload_sha256,
                payload_format=payload_format.value,
                raw_ingested_count=raw_ingested_count,
                priority_lane=priority_lane.value,
                window_start_utc=window_start_utc.isoformat(),
                window_end_utc=window_end_utc.isoformat(),
                trace_id=resolved_trace_id,
                correlation_id=correlation_id,
            )
        )
        return manifest

    def mark_processing(self) -> None:
        """Transitions manifest status to PROCESSING."""
        self.status = BatchManifestStatus.PROCESSING

    def promote_outage_clusters(
        self,
        clusters: tuple[FeederOutageCluster, ...],
    ) -> None:
        """Stages P0_CRITICAL FeederOutageClusterDetectedEvent for each storm-grouped feeder outage."""
        if not clusters:
            return
        self.promoted_outage_clusters_count += len(clusters)
        for cluster in clusters:
            self.add_trace_event(
                IpTraceEvent.create(
                    tenant_id=self.tenant_id,
                    trace_id=self.trace_id,
                    correlation_id=self.correlation_id,
                    event_type=IpTraceEventType.FEEDER_OUTAGE_PROMOTED.value,
                    stage=PipelineStage.HYDRATE,
                    status=TraceEventStatus.SUCCESS,
                    summary_message=(
                        f"Promoted P0_CRITICAL feeder outage cluster '{cluster.cluster_id}' on "
                        f"feeder '{cluster.feeder_id}' ({cluster.outage_meter_count} endpoints at 0.0V)."
                    ),
                )
            )
            self.add_domain_event(
                FeederOutageClusterDetectedEvent(
                    cluster_id=cluster.cluster_id,
                    tenant_id=self.tenant_id,
                    connection_id=self.connection_id,
                    batch_id=self.id,
                    feeder_id=cluster.feeder_id,
                    substation_id=cluster.substation_id,
                    outage_meter_count=cluster.outage_meter_count,
                    affected_meter_ids=cluster.affected_meter_ids,
                    outage_start_utc=cluster.outage_start_utc.isoformat(),
                    trace_id=self.trace_id,
                    correlation_id=self.correlation_id,
                )
            )

    def complete_reconciled(
        self,
        *,
        counts: BatchReconciliationCounts,
        l2_replica_uri: str | None = None,
        l3_canonical_uri: str | None = None,
        delivery_receipt_id: str | None = None,
    ) -> Result[BatchManifest, IntervalReconciliationImbalanceError]:
        """Completes the batch after verifying the Zero-Loss Accounting Equation."""
        if not counts.is_balanced():
            return Result.fail(
                IntervalReconciliationImbalanceError.for_counts(
                    batch_id=self.id,
                    raw_ingested=counts.raw_ingested,
                    duplicates_dropped=counts.duplicates_dropped,
                    valid_canonical=counts.valid_canonical,
                    quarantined_held=counts.quarantined_held,
                )
            )

        if self.raw_ingested_count > 0 and counts.raw_ingested != self.raw_ingested_count:
            return Result.fail(
                IntervalReconciliationImbalanceError.for_counts(
                    batch_id=self.id,
                    raw_ingested=self.raw_ingested_count,
                    duplicates_dropped=counts.duplicates_dropped,
                    valid_canonical=counts.valid_canonical,
                    quarantined_held=counts.quarantined_held,
                )
            )

        self.raw_ingested_count = counts.raw_ingested
        self.duplicates_dropped_count = counts.duplicates_dropped
        self.valid_canonical_count = counts.valid_canonical
        self.quarantined_held_count = counts.quarantined_held
        self.l2_replica_uri = l2_replica_uri
        self.l3_canonical_uri = l3_canonical_uri
        if delivery_receipt_id is not None:
            self.delivery_receipt_id = delivery_receipt_id
        self.status = BatchManifestStatus.COMPLETED
        self.completed_at = datetime.now(UTC)
        self.error_message = None

        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.INTERVAL_BATCH_NORMALIZED.value,
                stage=PipelineStage.NORMALIZE,
                status=TraceEventStatus.SUCCESS,
                summary_message=(
                    f"Completed vectorized normalization for batch '{self.id}': "
                    f"raw={counts.raw_ingested}, valid={counts.valid_canonical}, "
                    f"duplicates={counts.duplicates_dropped}, quarantined={counts.quarantined_held}."
                ),
            )
        )

        self.add_domain_event(
            IntervalBatchProcessedEvent(
                batch_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream_name=self.stream_name,
                raw_ingested_count=counts.raw_ingested,
                duplicates_dropped_count=counts.duplicates_dropped,
                valid_canonical_count=counts.valid_canonical,
                quarantined_held_count=counts.quarantined_held,
                promoted_outage_clusters_count=self.promoted_outage_clusters_count,
                l2_replica_uri=l2_replica_uri,
                l3_canonical_uri=l3_canonical_uri,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(self)

    def record_delivery_receipt(self, delivery_receipt_id: str) -> None:
        """Records a downstream settlement receipt ID (e.g. CIS / billing batch acknowledgement)."""
        self.delivery_receipt_id = delivery_receipt_id
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.SETTLEMENT_RECEIPT_RECORDED.value,
                stage=PipelineStage.DELIVER,
                status=TraceEventStatus.SUCCESS,
                summary_message=(
                    f"Recorded downstream delivery receipt '{delivery_receipt_id}' for batch '{self.id}'."
                ),
            )
        )

    def mark_failed(self, error_message: str) -> None:
        """Marks the batch manifest as FAILED with diagnostic message."""
        self.status = BatchManifestStatus.FAILED
        self.error_message = error_message
        self.completed_at = datetime.now(UTC)
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.NORMALIZATION_FAILED.value,
                stage=PipelineStage.NORMALIZE,
                status=TraceEventStatus.FAILED,
                summary_message=f"Interval batch '{self.id}' failed: {error_message}",
            )
        )


__all__ = [
    "BatchManifest",
    "BatchReconciliationCounts",
    "BatchReconciliationSummary",
    "DailyTouBillingRollup",
    "FeederOutageCluster",
    "HourlyIntervalRollup",
    "IntervalLineageTrace",
    "IntervalReading",
    "IntervalWindowCompleteness",
    "StormAggregationPolicy",
    "VeeValidationPolicy",
]
