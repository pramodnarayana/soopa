import type { SyncRunKindValue, SyncRunStatusValue } from './enums';

export interface SyncRun {
  readonly runId: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly streamName: string;
  readonly kind: SyncRunKindValue | (string & {});
  readonly generationId: number;
  readonly status: SyncRunStatusValue;
  readonly startCheckpoint: string | null;
  readonly endCheckpoint: string | null;
  readonly pagesCount: number;
  readonly recordsCount: number;
  readonly bytesCount: number;
  readonly retryCount: number;
  readonly errorCode: string | null;
  readonly errorMessage: string | null;
  readonly traceId: string;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly createdAt: string;
}

export interface StreamState {
  readonly stateId: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly streamName: string;
  readonly cursorField: string | null;
  readonly cursorValue: string | null;
  readonly recordsSyncedCount: number;
  readonly lastSyncedAt: string;
}

export interface TriggerSyncRunInput {
  readonly streamName: string;
  readonly forcedKind?: SyncRunKindValue | null;
  readonly correlationId?: string | null;
}
