import type {
  BatchManifestSummary,
  BatchReconciliationOverview,
  DailyTouRollup,
  IntervalLineagePoint,
  IntervalLineageTrace,
  IntervalWindowCompleteness,
} from '../../../domain/intervals';
import type {
  BatchManifestSummaryWire,
  BatchReconciliationOverviewWire,
  DailyTouRollupWire,
  IntervalLineagePointWire,
  IntervalLineageTraceWire,
  IntervalWindowCompletenessWire,
} from '../schemas/interval.schema';

export function mapBatchManifestFromWire(wire: BatchManifestSummaryWire): BatchManifestSummary {
  return {
    batchId: wire.batch_id,
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    priorityLane: wire.priority_lane,
    status: wire.status,
    l1RawUri: wire.l1_raw_uri,
    l2ReplicaUri: wire.l2_replica_uri,
    l3CanonicalUri: wire.l3_canonical_uri,
    payloadSha256: wire.payload_sha256,
    rawIngestedCount: wire.raw_ingested_count,
    duplicatesDroppedCount: wire.duplicates_dropped_count,
    validCanonicalCount: wire.valid_canonical_count,
    quarantinedHeldCount: wire.quarantined_held_count,
    promotedOutageClustersCount: wire.promoted_outage_clusters_count,
    deliveryReceiptId: wire.delivery_receipt_id,
    traceId: wire.trace_id,
    createdAt: wire.created_at,
    completedAt: wire.completed_at,
  };
}

export function mapReconciliationOverviewFromWire(
  wire: BatchReconciliationOverviewWire,
): BatchReconciliationOverview {
  return {
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    totalBatches: wire.total_batches,
    completedBatches: wire.completed_batches,
    inFlightBatches: wire.in_flight_batches,
    failedBatches: wire.failed_batches,
    rawIngestedTotal: wire.raw_ingested_total,
    duplicatesDroppedTotal: wire.duplicates_dropped_total,
    validCanonicalTotal: wire.valid_canonical_total,
    quarantinedHeldTotal: wire.quarantined_held_total,
    inFlightReadingsTotal: wire.in_flight_readings_total,
    isZeroLossBalanced: wire.is_zero_loss_balanced,
    recentBatches: wire.recent_batches.map(mapBatchManifestFromWire),
  };
}

export function mapCompletenessFromWire(
  wire: IntervalWindowCompletenessWire,
): IntervalWindowCompleteness {
  return {
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    serviceDate: wire.service_date,
    feederId: wire.feeder_id,
    expectedIntervalsPerDevice: wire.expected_intervals_per_meter,
    activeDeviceCount: wire.active_meter_count,
    expectedIntervalsTotal: wire.expected_intervals_total,
    receivedIntervalsTotal: wire.received_intervals_total,
    validIntervalsTotal: wire.valid_intervals_total,
    quarantinedIntervalsTotal: wire.quarantined_intervals_total,
    completenessPercentage: wire.completeness_percentage,
  };
}

export function mapDailyTouRollupFromWire(wire: DailyTouRollupWire): DailyTouRollup {
  return {
    tenantId: wire.tenant_id,
    gemDeviceId: wire.gem_device_id,
    sourceDeviceId: wire.source_meter_id,
    serviceDate: wire.service_date,
    feederId: wire.feeder_id,
    peakVolume: wire.kwh_peak,
    shoulderVolume: wire.kwh_shoulder,
    offPeakVolume: wire.kwh_off_peak,
    netExportVolume: wire.kwh_net_export,
    maxDemandKw: wire.max_kw_demand,
    validIntervals: wire.valid_intervals,
    quarantinedIntervals: wire.quarantined_intervals,
    latestBatchId: wire.latest_batch_id,
    deliveryReceiptId: wire.delivery_receipt_id,
  };
}

export function mapIntervalLineagePointFromWire(
  wire: IntervalLineagePointWire,
): IntervalLineagePoint {
  return {
    intervalEndUtc: wire.interval_end_utc,
    gemDeviceId: wire.gem_device_id,
    sourceDeviceId: wire.source_meter_id,
    endpointLocationId: wire.endpoint_location_id,
    feederId: wire.feeder_id,
    substationId: wire.substation_id,
    tariffBucket: wire.tariff_bucket,
    qualityStatus: wire.quality_status,
    deliveredVolume: wire.scaled_kwh_delivered,
    receivedVolume: wire.scaled_kwh_received,
    reactiveVolume: wire.reactive_kvarh,
    voltageV: wire.voltage_v,
    quarantineReason: wire.quarantine_reason,
    sourceBatchId: wire.source_batch_id,
    parquetRowOffset: wire.parquet_row_offset,
    batchStatus: wire.batch_status,
    priorityLane: wire.priority_lane,
    l1RawUri: wire.l1_raw_uri,
    l2ReplicaUri: wire.l2_replica_uri,
    l3CanonicalUri: wire.l3_canonical_uri,
    payloadSha256: wire.payload_sha256,
    deliveryReceiptId: wire.delivery_receipt_id,
    traceId: wire.trace_id,
  };
}

export function mapIntervalLineageTraceFromWire(
  wire: IntervalLineageTraceWire,
): IntervalLineageTrace {
  return {
    tenantId: wire.tenant_id,
    sourceDeviceId: wire.source_meter_id,
    serviceDate: wire.service_date,
    totalIntervals: wire.total_intervals,
    validIntervals: wire.valid_intervals,
    quarantinedIntervals: wire.quarantined_intervals,
    intervals: wire.intervals.map(mapIntervalLineagePointFromWire),
  };
}
