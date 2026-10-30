import type {
  BulkReplayResult,
  InboundRecord,
  IpTrace,
  IpTraceLineageItem,
  NormalizedRecord,
  OutboundRecord,
  ReplayTransactionResult,
  ReplicaRecord,
} from '../../../domain/trace';
import type {
  BulkReplayResultWire,
  InboundRecordWire,
  IpTraceLineageItemWire,
  IpTraceWire,
  NormalizedRecordWire,
  OutboundRecordWire,
  ReplayTransactionResultWire,
  ReplicaRecordWire,
} from '../schemas/trace.schema';

function mapInboundFromWire(wire: InboundRecordWire): InboundRecord {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    parentTraceId: wire.parent_trace_id,
    originalTraceId: wire.original_trace_id,
    replayCount: wire.replay_count,
    connectionId: wire.connection_id,
    appId: wire.app_id,
    streamName: wire.stream_name,
    ingestionMode: wire.ingestion_mode,
    syncRunId: wire.sync_run_id,
    generationId: wire.generation_id,
    externalEventId: wire.external_event_id,
    requestHeaders: wire.request_headers,
    requestBody: wire.request_body,
    requestS3Key: wire.request_s3_key,
    requestSizeBytes: wire.request_size_bytes,
    requestSha256: wire.request_sha256,
    responseStatusCode: wire.response_status_code,
    responseHeaders: wire.response_headers,
    responseBody: wire.response_body,
    responseS3Key: wire.response_s3_key,
    durationMs: wire.duration_ms,
    receivedAt: wire.received_at,
  };
}

function mapReplicaFromWire(wire: ReplicaRecordWire): ReplicaRecord {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    parentTraceId: wire.parent_trace_id,
    originalTraceId: wire.original_trace_id,
    replayCount: wire.replay_count,
    connectionId: wire.connection_id,
    stream: wire.stream,
    recordKey: wire.record_key,
    primaryKeyValues: wire.primary_key_values,
    cursorValue: wire.cursor_value,
    cursorKind: wire.cursor_kind,
    data: wire.data,
    dataHash: wire.data_hash,
    version: wire.version,
    generationId: wire.generation_id,
    lastSeenGeneration: wire.last_seen_generation,
    firstSeenAt: wire.first_seen_at,
    extractedAt: wire.extracted_at,
    updatedAt: wire.updated_at,
    deletedAt: wire.deleted_at,
    sourceInboundRecordId: wire.source_inbound_record_id,
  };
}

function mapNormalizedFromWire(wire: NormalizedRecordWire): NormalizedRecord {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    parentTraceId: wire.parent_trace_id,
    originalTraceId: wire.original_trace_id,
    replayCount: wire.replay_count,
    connectionId: wire.connection_id,
    canonicalType: wire.canonical_type,
    sourceId: wire.source_id,
    canonicalData: wire.canonical_data,
    normalizedAt: wire.normalized_at,
  };
}

function mapOutboundFromWire(wire: OutboundRecordWire): OutboundRecord {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    parentTraceId: wire.parent_trace_id,
    originalTraceId: wire.original_trace_id,
    replayCount: wire.replay_count,
    connectionId: wire.connection_id,
    appId: wire.app_id,
    streamName: wire.stream_name,
    operation: wire.operation,
    idempotencyKey: wire.idempotency_key,
    externalRecordId: wire.external_record_id,
    targetUrl: wire.target_url,
    httpMethod: wire.http_method,
    requestHeaders: wire.request_headers,
    requestBody: wire.request_body,
    requestS3Key: wire.request_s3_key,
    requestSizeBytes: wire.request_size_bytes,
    requestSha256: wire.request_sha256,
    status: wire.status,
    responseStatusCode: wire.response_status_code,
    responseHeaders: wire.response_headers,
    responseBody: wire.response_body,
    responseS3Key: wire.response_s3_key,
    durationMs: wire.duration_ms,
    attemptNumber: wire.attempt_number,
    failureCategory: wire.failure_category,
    retryAfterSeconds: wire.retry_after_seconds,
    errorMessage: wire.error_message,
    sentAt: wire.sent_at,
  };
}

export function mapIpTraceFromWire(wire: IpTraceWire): IpTrace {
  return {
    traceId: wire.trace_id,
    tenantId: wire.tenant_id,
    correlationId: wire.correlation_id,
    originalTraceId: wire.original_trace_id,
    parentTraceId: wire.parent_trace_id,
    replayCount: wire.replay_count,
    status: wire.status,
    inboundRecord: wire.inbound_record ? mapInboundFromWire(wire.inbound_record) : null,
    replicaRecords: wire.replica_records.map(mapReplicaFromWire),
    replicaRejections: wire.replica_rejections.map((rej) => ({
      id: rej.id,
      tenantId: rej.tenant_id,
      connectionId: rej.connection_id,
      stream: rej.stream,
      inboundRecordId: rej.inbound_record_id,
      recordIndex: rej.record_index,
      reason: rej.reason,
      detail: rej.detail,
      traceId: rej.trace_id,
      createdAt: rej.created_at,
    })),
    normalizedRecords: wire.normalized_records.map(mapNormalizedFromWire),
    normalizationRejections: wire.normalization_rejections.map((rej) => ({
      id: rej.id,
      tenantId: rej.tenant_id,
      replicaRecordId: rej.replica_record_id,
      stream: rej.stream,
      transformationId: rej.transformation_id,
      transformationVersion: rej.transformation_version,
      reasonCode: rej.reason_code,
      fieldPath: rej.field_path,
      detail: rej.detail,
      traceId: rej.trace_id,
      correlationId: rej.correlation_id,
      createdAt: rej.created_at,
    })),
    entityMappings: wire.entity_mappings.map((gem) => ({
      id: gem.id,
      tenantId: gem.tenant_id,
      traceId: gem.trace_id,
      correlationId: gem.correlation_id,
      parentTraceId: gem.parent_trace_id,
      originalTraceId: gem.original_trace_id,
      replayCount: gem.replay_count,
      entityDomain: gem.entity_domain,
      canonicalId: gem.canonical_id,
      sourceConnectionId: gem.source_connection_id,
      sourceEntityId: gem.source_entity_id,
      destConnectionId: gem.dest_connection_id,
      destEntityId: gem.dest_entity_id,
      createdAt: gem.created_at,
    })),
    outboundRecords: wire.outbound_records.map(mapOutboundFromWire),
    traceEvents: wire.trace_events.map((evt) => ({
      id: evt.id,
      tenantId: evt.tenant_id,
      traceId: evt.trace_id,
      eventType: evt.event_type,
      actor: evt.actor,
      correlationId: evt.correlation_id,
      createdAt: evt.created_at,
      metadata: evt.metadata,
    })),
  };
}

export function mapLineageItemFromWire(wire: IpTraceLineageItemWire): IpTraceLineageItem {
  return {
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    status: wire.status,
    primaryLayer: wire.primary_layer,
    createdAt: wire.created_at,
    replayCount: wire.replay_count,
    parentTraceId: wire.parent_trace_id,
    originalTraceId: wire.original_trace_id,
  };
}

export function mapReplayResultFromWire(
  wire: ReplayTransactionResultWire,
): ReplayTransactionResult {
  return {
    status: wire.status,
    originalTraceId: wire.original_trace_id,
    parentTraceId: wire.parent_trace_id,
    newTraceId: wire.new_trace_id,
    stage: wire.stage,
    replayCount: wire.replay_count,
    correlationId: wire.correlation_id,
  };
}

export function mapBulkReplayResultFromWire(wire: BulkReplayResultWire): BulkReplayResult {
  return {
    status: wire.status,
    stage: wire.stage,
    replayedCount: wire.replayed_count,
    succeededTraceIds: wire.succeeded_trace_ids,
    newTraceIds: wire.new_trace_ids,
    failedItems: wire.failed_items.map((item) => ({
      traceId: item.trace_id,
      errorCode: item.error_code,
      message: item.message,
    })),
  };
}
