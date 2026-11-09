"""Pydantic HTTP boundary DTOs for the High-Frequency Interval Streams API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class IntervalBatchIngressHttpResponse(BaseModel):
    """HTTP 202 response for L1 Shock-Absorber interval macro-batch ingestion."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    status: str
    priority_lane: str
    l1_raw_uri: str
    payload_sha256: str
    payload_size_bytes: int
    raw_ingested_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    trace_id: str
    is_duplicate: bool = False


class FeederOutageClusterHttpDTO(BaseModel):
    """HTTP representation of a storm-promoted FeederOutageCluster."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    feeder_id: str
    substation_id: str
    outage_meter_count: int
    affected_meter_ids: list[str]
    outage_start_utc: datetime
    trace_id: str


class IntervalBatchProcessHttpResponse(BaseModel):
    """HTTP response for vectorized L2/L3 interval batch normalization and Zero-Loss reconciliation."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    status: str
    raw_ingested: int
    duplicates_dropped: int
    valid_canonical: int
    quarantined_held: int
    is_zero_loss_balanced: bool
    promoted_outage_clusters: list[FeederOutageClusterHttpDTO]
    l2_replica_uri: str | None = None
    l3_canonical_uri: str | None = None
    trace_id: str
    is_already_processed: bool = False


class BatchManifestSummaryHttpDTO(BaseModel):
    """HTTP summary of a BatchManifest in `ip_batch_manifests`."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    connection_id: str
    stream_name: str
    priority_lane: str
    status: str
    l1_raw_uri: str
    l2_replica_uri: str | None = None
    l3_canonical_uri: str | None = None
    payload_sha256: str
    raw_ingested_count: int
    duplicates_dropped_count: int
    valid_canonical_count: int
    quarantined_held_count: int
    promoted_outage_clusters_count: int
    delivery_receipt_id: str | None = None
    trace_id: str
    created_at: datetime
    completed_at: datetime | None = None


class BatchReconciliationOverviewHttpResponse(BaseModel):
    """HTTP response for the Command Center Zero-Missing-Data Guarantee Bar."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    connection_id: str | None = None
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
    recent_batches: list[BatchManifestSummaryHttpDTO]


class IntervalWindowCompletenessHttpDTO(BaseModel):
    """HTTP representation of a 96-slot daily interval completeness ribbon entry."""

    model_config = ConfigDict(extra="forbid")

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


class DailyTouRollupHttpDTO(BaseModel):
    """HTTP representation of a Daily Time-of-Use (TOU) Peak/Shoulder/Off-Peak billing rollup."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    gem_device_id: str
    source_meter_id: str
    service_date: date
    feeder_id: str
    kwh_peak: str
    kwh_shoulder: str
    kwh_off_peak: str
    kwh_net_export: str
    max_kw_demand: str
    valid_intervals: int
    quarantined_intervals: int
    latest_batch_id: str
    delivery_receipt_id: str | None = None


class IntervalLineageHttpDTO(BaseModel):
    """Two-Tier Trace Linkage item joining a 15-min interval reading to its macro-batch L1-L5 lineage."""

    model_config = ConfigDict(extra="forbid")

    interval_end_utc: datetime
    gem_device_id: str
    source_meter_id: str
    endpoint_location_id: str
    feeder_id: str
    substation_id: str
    tariff_bucket: str
    quality_status: str
    scaled_kwh_delivered: str
    scaled_kwh_received: str
    reactive_kvarh: str
    voltage_v: float
    quarantine_reason: str | None = None
    source_batch_id: str
    parquet_row_offset: int
    batch_status: str
    priority_lane: str
    l1_raw_uri: str
    l2_replica_uri: str | None = None
    l3_canonical_uri: str | None = None
    payload_sha256: str
    delivery_receipt_id: str | None = None
    trace_id: str


class IntervalLineageTraceHttpResponse(BaseModel):
    """Two-Tier Trace Linkage response for a device's 96-slot daily load curve."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_meter_id: str
    service_date: date
    total_intervals: int
    valid_intervals: int
    quarantined_intervals: int
    intervals: list[IntervalLineageHttpDTO]


class RecordSettlementReceiptHttpRequest(BaseModel):
    """Request body for recording a downstream settlement receipt ID."""

    model_config = ConfigDict(extra="forbid")

    delivery_receipt_id: str = Field(..., min_length=1, max_length=128)


__all__ = [
    "BatchManifestSummaryHttpDTO",
    "BatchReconciliationOverviewHttpResponse",
    "DailyTouRollupHttpDTO",
    "FeederOutageClusterHttpDTO",
    "IntervalBatchIngressHttpResponse",
    "IntervalBatchProcessHttpResponse",
    "IntervalLineageHttpDTO",
    "IntervalLineageTraceHttpResponse",
    "IntervalWindowCompletenessHttpDTO",
    "RecordSettlementReceiptHttpRequest",
]
