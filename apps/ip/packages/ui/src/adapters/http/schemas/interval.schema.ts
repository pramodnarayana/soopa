import { z } from 'zod';

export const BatchManifestSummaryWireSchema = z.object({
  batch_id: z.string(),
  connection_id: z.string(),
  stream_name: z.string(),
  priority_lane: z.string(),
  status: z.string(),
  l1_raw_uri: z.string(),
  l2_replica_uri: z.string().nullable(),
  l3_canonical_uri: z.string().nullable(),
  payload_sha256: z.string(),
  raw_ingested_count: z.number(),
  duplicates_dropped_count: z.number(),
  valid_canonical_count: z.number(),
  quarantined_held_count: z.number(),
  promoted_outage_clusters_count: z.number(),
  delivery_receipt_id: z.string().nullable(),
  trace_id: z.string(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});
export type BatchManifestSummaryWire = z.infer<typeof BatchManifestSummaryWireSchema>;

export const BatchReconciliationOverviewWireSchema = z.object({
  tenant_id: z.string(),
  connection_id: z.string().nullable(),
  total_batches: z.number(),
  completed_batches: z.number(),
  in_flight_batches: z.number(),
  failed_batches: z.number(),
  raw_ingested_total: z.number(),
  duplicates_dropped_total: z.number(),
  valid_canonical_total: z.number(),
  quarantined_held_total: z.number(),
  in_flight_readings_total: z.number(),
  is_zero_loss_balanced: z.boolean(),
  recent_batches: z.array(BatchManifestSummaryWireSchema),
});
export type BatchReconciliationOverviewWire = z.infer<typeof BatchReconciliationOverviewWireSchema>;

export const IntervalWindowCompletenessWireSchema = z.object({
  tenant_id: z.string(),
  connection_id: z.string(),
  stream_name: z.string(),
  service_date: z.string(),
  feeder_id: z.string(),
  expected_intervals_per_meter: z.number(),
  active_meter_count: z.number(),
  expected_intervals_total: z.number(),
  received_intervals_total: z.number(),
  valid_intervals_total: z.number(),
  quarantined_intervals_total: z.number(),
  completeness_percentage: z.number(),
});
export const IntervalWindowCompletenessListWireSchema = z.array(
  IntervalWindowCompletenessWireSchema,
);
export type IntervalWindowCompletenessWire = z.infer<typeof IntervalWindowCompletenessWireSchema>;

export const DailyTouRollupWireSchema = z.object({
  tenant_id: z.string(),
  gem_device_id: z.string(),
  source_meter_id: z.string(),
  service_date: z.string(),
  feeder_id: z.string(),
  kwh_peak: z.string(),
  kwh_shoulder: z.string(),
  kwh_off_peak: z.string(),
  kwh_net_export: z.string(),
  max_kw_demand: z.string(),
  valid_intervals: z.number(),
  quarantined_intervals: z.number(),
  latest_batch_id: z.string(),
  connection_id: z.string().optional().default(''),
  delivery_receipt_id: z.string().nullable(),
});
export const DailyTouRollupListWireSchema = z.array(DailyTouRollupWireSchema);
export type DailyTouRollupWire = z.infer<typeof DailyTouRollupWireSchema>;

export const IntervalLineagePointWireSchema = z.object({
  interval_end_utc: z.string(),
  gem_device_id: z.string(),
  source_meter_id: z.string(),
  endpoint_location_id: z.string(),
  feeder_id: z.string(),
  substation_id: z.string(),
  tariff_bucket: z.string(),
  quality_status: z.string(),
  scaled_kwh_delivered: z.string(),
  scaled_kwh_received: z.string(),
  reactive_kvarh: z.string(),
  voltage_v: z.number(),
  quarantine_reason: z.string().nullable(),
  source_batch_id: z.string(),
  parquet_row_offset: z.number(),
  batch_status: z.string(),
  priority_lane: z.string(),
  l1_raw_uri: z.string(),
  l2_replica_uri: z.string().nullable(),
  l3_canonical_uri: z.string().nullable(),
  payload_sha256: z.string(),
  delivery_receipt_id: z.string().nullable(),
  trace_id: z.string(),
});
export type IntervalLineagePointWire = z.infer<typeof IntervalLineagePointWireSchema>;

export const IntervalLineageTraceWireSchema = z.object({
  tenant_id: z.string(),
  source_meter_id: z.string(),
  service_date: z.string(),
  total_intervals: z.number(),
  valid_intervals: z.number(),
  quarantined_intervals: z.number(),
  intervals: z.array(IntervalLineagePointWireSchema),
});
export type IntervalLineageTraceWire = z.infer<typeof IntervalLineageTraceWireSchema>;
