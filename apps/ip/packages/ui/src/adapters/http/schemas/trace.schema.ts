import { z } from 'zod';

const JsonPrimitiveWireSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
const JsonRecordWireSchema = z.record(z.string(), z.unknown());

export const InboundRecordWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  connection_id: z.string(),
  app_id: z.string(),
  stream_name: z.string(),
  ingestion_mode: z.string(),
  sync_run_id: z.string().nullable().optional().default(null),
  generation_id: z.number().nullable().optional().default(null),
  external_event_id: z.string().nullable().optional().default(null),
  request_headers: JsonRecordWireSchema.default({}),
  request_body: JsonRecordWireSchema.nullable().optional().default(null),
  request_s3_key: z.string().nullable().optional().default(null),
  request_size_bytes: z.number(),
  request_sha256: z.string(),
  response_status_code: z.number().nullable().optional().default(null),
  response_headers: JsonRecordWireSchema.nullable().optional().default(null),
  response_body: JsonRecordWireSchema.nullable().optional().default(null),
  response_s3_key: z.string().nullable().optional().default(null),
  duration_ms: z.number().nullable().optional().default(null),
  received_at: z.string(),
});

export const ReplicaRecordWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  connection_id: z.string(),
  stream: z.string(),
  record_key: z.string(),
  primary_key_values: z.array(JsonPrimitiveWireSchema).default([]),
  cursor_value: z.string().nullable().optional().default(null),
  cursor_kind: z.string().nullable().optional().default(null),
  data: JsonRecordWireSchema.default({}),
  data_hash: z.string(),
  version: z.number(),
  generation_id: z.number(),
  last_seen_generation: z.number(),
  first_seen_at: z.string(),
  extracted_at: z.string(),
  updated_at: z.string(),
  deleted_at: z.string().nullable().optional().default(null),
  source_inbound_record_id: z.string(),
});

export const ReplicaRejectionWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  stream: z.string(),
  inbound_record_id: z.string(),
  record_index: z.number(),
  reason: z.string(),
  detail: z.string(),
  trace_id: z.string(),
  created_at: z.string(),
});

export const NormalizedRecordWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  connection_id: z.string(),
  canonical_type: z.string(),
  source_id: z.string(),
  canonical_data: JsonRecordWireSchema.default({}),
  normalized_at: z.string(),
});

export const NormalizationRejectionWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  replica_record_id: z.string(),
  stream: z.string(),
  transformation_id: z.string(),
  transformation_version: z.number(),
  reason_code: z.string(),
  field_path: z.string().nullable().optional().default(null),
  detail: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  created_at: z.string(),
});

export const GlobalEntityMapWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  entity_domain: z.string(),
  canonical_id: z.string(),
  source_connection_id: z.string(),
  source_entity_id: z.string(),
  dest_connection_id: z.string().nullable().optional().default(null),
  dest_entity_id: z.string().nullable().optional().default(null),
  created_at: z.string(),
});

export const OutboundRecordWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  connection_id: z.string(),
  app_id: z.string(),
  stream_name: z.string(),
  operation: z.string(),
  idempotency_key: z.string().nullable().optional().default(null),
  external_record_id: z.string().nullable().optional().default(null),
  target_url: z.string(),
  http_method: z.string(),
  request_headers: JsonRecordWireSchema.default({}),
  request_body: JsonRecordWireSchema.nullable().optional().default(null),
  request_s3_key: z.string().nullable().optional().default(null),
  request_size_bytes: z.number(),
  request_sha256: z.string(),
  status: z.string(),
  response_status_code: z.number().nullable().optional().default(null),
  response_headers: JsonRecordWireSchema.nullable().optional().default(null),
  response_body: JsonRecordWireSchema.nullable().optional().default(null),
  response_s3_key: z.string().nullable().optional().default(null),
  duration_ms: z.number().nullable().optional().default(null),
  attempt_number: z.number(),
  failure_category: z.string().nullable().optional().default(null),
  retry_after_seconds: z.number().nullable().optional().default(null),
  error_message: z.string().nullable().optional().default(null),
  sent_at: z.string(),
});

export const TraceEventWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  trace_id: z.string(),
  event_type: z.string(),
  actor: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  created_at: z.string(),
  metadata: JsonRecordWireSchema.nullable().optional().default(null),
});

export const IpTraceWireSchema = z.object({
  trace_id: z.string(),
  tenant_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string(),
  parent_trace_id: z.string().nullable().optional().default(null),
  replay_count: z.number(),
  status: z.string(),
  inbound_record: InboundRecordWireSchema.nullable().optional().default(null),
  replica_records: z.array(ReplicaRecordWireSchema).default([]),
  replica_rejections: z.array(ReplicaRejectionWireSchema).default([]),
  normalized_records: z.array(NormalizedRecordWireSchema).default([]),
  normalization_rejections: z.array(NormalizationRejectionWireSchema).default([]),
  entity_mappings: z.array(GlobalEntityMapWireSchema).default([]),
  outbound_records: z.array(OutboundRecordWireSchema).default([]),
  trace_events: z.array(TraceEventWireSchema).default([]),
});

export const IpTraceLineageItemWireSchema = z.object({
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  status: z.string(),
  primary_layer: z.string(),
  created_at: z.string().nullable().optional().default(null),
  replay_count: z.number().default(0),
  parent_trace_id: z.string().nullable().optional().default(null),
  original_trace_id: z.string().nullable().optional().default(null),
});

export const IpTraceLineageListWireSchema = z.array(IpTraceLineageItemWireSchema);

export const ReplayTransactionResultWireSchema = z.object({
  status: z.string(),
  original_trace_id: z.string(),
  parent_trace_id: z.string(),
  new_trace_id: z.string(),
  stage: z.string(),
  replay_count: z.number(),
  correlation_id: z.string().nullable().optional().default(null),
});

export const BulkReplayResultWireSchema = z.object({
  status: z.string(),
  stage: z.string(),
  replayed_count: z.number(),
  succeeded_trace_ids: z.array(z.string()).default([]),
  new_trace_ids: z.array(z.string()).default([]),
  failed_items: z
    .array(
      z.object({
        trace_id: z.string(),
        error_code: z.string(),
        message: z.string(),
      }),
    )
    .default([]),
});

export type InboundRecordWire = z.infer<typeof InboundRecordWireSchema>;
export type ReplicaRecordWire = z.infer<typeof ReplicaRecordWireSchema>;
export type NormalizedRecordWire = z.infer<typeof NormalizedRecordWireSchema>;
export type OutboundRecordWire = z.infer<typeof OutboundRecordWireSchema>;
export type IpTraceWire = z.infer<typeof IpTraceWireSchema>;
export type IpTraceLineageItemWire = z.infer<typeof IpTraceLineageItemWireSchema>;
export type ReplayTransactionResultWire = z.infer<typeof ReplayTransactionResultWireSchema>;
export type BulkReplayResultWire = z.infer<typeof BulkReplayResultWireSchema>;
