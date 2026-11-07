import type {
  JsonPrimitive,
  JsonRecord,
  PipelineLayerValue,
  ReplayDispatchStatusValue,
  ReplayStageValue,
  TraceStatusValue,
} from './enums';

export interface InboundRecord {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
  readonly replayCount: number;
  readonly connectionId: string;
  readonly appId: string;
  readonly streamName: string;
  readonly ingestionMode: string;
  readonly syncRunId: string | null;
  readonly generationId: number | null;
  readonly externalEventId: string | null;
  readonly requestHeaders: JsonRecord;
  readonly requestBody: JsonRecord | null;
  readonly requestS3Key: string | null;
  readonly requestSizeBytes: number;
  readonly requestSha256: string;
  readonly responseStatusCode: number | null;
  readonly responseHeaders: JsonRecord | null;
  readonly responseBody: JsonRecord | null;
  readonly responseS3Key: string | null;
  readonly durationMs: number | null;
  readonly receivedAt: string;
}

export interface ReplicaRecord {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
  readonly replayCount: number;
  readonly connectionId: string;
  readonly stream: string;
  readonly recordKey: string;
  readonly primaryKeyValues: readonly JsonPrimitive[];
  readonly cursorValue: string | null;
  readonly cursorKind: string | null;
  readonly data: JsonRecord;
  readonly dataHash: string;
  readonly version: number;
  readonly generationId: number;
  readonly lastSeenGeneration: number;
  readonly firstSeenAt: string;
  readonly extractedAt: string;
  readonly updatedAt: string;
  readonly deletedAt: string | null;
  readonly sourceInboundRecordId: string;
}

export interface ReplicaRejection {
  readonly id: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly stream: string;
  readonly inboundRecordId: string;
  readonly recordIndex: number;
  readonly reason: string;
  readonly detail: string;
  readonly traceId: string;
  readonly createdAt: string;
}

export interface NormalizedRecord {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
  readonly replayCount: number;
  readonly connectionId: string;
  readonly canonicalType: string;
  readonly sourceId: string;
  readonly canonicalData: JsonRecord;
  readonly normalizedAt: string;
}

export interface NormalizationRejection {
  readonly id: string;
  readonly tenantId: string;
  readonly replicaRecordId: string;
  readonly stream: string;
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly reasonCode: string;
  readonly fieldPath: string | null;
  readonly detail: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly createdAt: string;
}

export interface GlobalEntityMapEntry {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
  readonly replayCount: number;
  readonly entityDomain: string;
  readonly canonicalId: string;
  readonly sourceConnectionId: string;
  readonly sourceEntityId: string;
  readonly destConnectionId: string | null;
  readonly destEntityId: string | null;
  readonly createdAt: string;
}

export interface OutboundRecord {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
  readonly replayCount: number;
  readonly connectionId: string;
  readonly appId: string;
  readonly streamName: string;
  readonly operation: string;
  readonly idempotencyKey: string | null;
  readonly externalRecordId: string | null;
  readonly targetUrl: string;
  readonly httpMethod: string;
  readonly requestHeaders: JsonRecord;
  readonly requestBody: JsonRecord | null;
  readonly requestS3Key: string | null;
  readonly requestSizeBytes: number;
  readonly requestSha256: string;
  readonly status: string;
  readonly responseStatusCode: number | null;
  readonly responseHeaders: JsonRecord | null;
  readonly responseBody: JsonRecord | null;
  readonly responseS3Key: string | null;
  readonly durationMs: number | null;
  readonly attemptNumber: number;
  readonly failureCategory: string | null;
  readonly retryAfterSeconds: number | null;
  readonly errorMessage: string | null;
  readonly sentAt: string;
}

export interface TraceEventEntry {
  readonly id: string;
  readonly tenantId: string;
  readonly traceId: string;
  readonly eventType: string;
  readonly actor: string;
  readonly correlationId: string | null;
  readonly createdAt: string;
  readonly metadata: JsonRecord | null;
}

export interface IpTrace {
  readonly traceId: string;
  readonly tenantId: string;
  readonly correlationId: string | null;
  readonly originalTraceId: string;
  readonly parentTraceId: string | null;
  readonly replayCount: number;
  readonly status: TraceStatusValue;
  readonly inboundRecord: InboundRecord | null;
  readonly replicaRecords: readonly ReplicaRecord[];
  readonly replicaRejections: readonly ReplicaRejection[];
  readonly normalizedRecords: readonly NormalizedRecord[];
  readonly normalizationRejections: readonly NormalizationRejection[];
  readonly entityMappings: readonly GlobalEntityMapEntry[];
  readonly outboundRecords: readonly OutboundRecord[];
  readonly traceEvents: readonly TraceEventEntry[];
}

export interface IpTraceLineageItem {
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly status: TraceStatusValue;
  readonly primaryLayer: PipelineLayerValue | (string & {});
  readonly createdAt: string | null;
  readonly replayCount: number;
  readonly parentTraceId: string | null;
  readonly originalTraceId: string | null;
}

export interface ReplayTransactionResult {
  readonly status: ReplayDispatchStatusValue;
  readonly originalTraceId: string;
  readonly parentTraceId: string;
  readonly newTraceId: string;
  readonly stage: ReplayStageValue | (string & {});
  readonly replayCount: number;
  readonly correlationId: string | null;
}

export interface BulkReplayFailureItem {
  readonly traceId: string;
  readonly errorCode: string;
  readonly message: string;
}

export interface BulkReplayResult {
  readonly status: ReplayDispatchStatusValue;
  readonly stage: ReplayStageValue | (string & {});
  readonly replayedCount: number;
  readonly succeededTraceIds: readonly string[];
  readonly newTraceIds: readonly string[];
  readonly failedItems: readonly BulkReplayFailureItem[];
}

export interface ListRecentTracesFilter {
  readonly status?: string;
  readonly minReplayCount?: number;
  readonly limit?: number;
}
