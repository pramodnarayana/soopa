import type { StreamState, SyncRun, TriggerSyncRunInput } from '../../../domain/sync-run';
import type { StreamStateWire, SyncRunWire } from '../schemas/sync-run.schema';

export function mapSyncRunFromWire(wire: SyncRunWire): SyncRun {
  return {
    runId: wire.run_id,
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    kind: wire.kind,
    generationId: wire.generation_id,
    status: wire.status,
    startCheckpoint: wire.start_checkpoint,
    endCheckpoint: wire.end_checkpoint,
    pagesCount: wire.pages_count,
    recordsCount: wire.records_count,
    bytesCount: wire.bytes_count,
    retryCount: wire.retry_count,
    errorCode: wire.error_code,
    errorMessage: wire.error_message,
    traceId: wire.trace_id,
    startedAt: wire.started_at,
    finishedAt: wire.finished_at,
    createdAt: wire.created_at,
  };
}

export function mapStreamStateFromWire(wire: StreamStateWire): StreamState {
  return {
    stateId: wire.state_id,
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    cursorField: wire.cursor_field,
    cursorValue: wire.cursor_value,
    recordsSyncedCount: wire.records_synced_count,
    lastSyncedAt: wire.last_synced_at,
  };
}

export function mapTriggerSyncRunToWire(input: TriggerSyncRunInput): Record<string, unknown> {
  return {
    stream_name: input.streamName,
    forced_kind: input.forcedKind ?? null,
    correlation_id: input.correlationId ?? null,
  };
}
