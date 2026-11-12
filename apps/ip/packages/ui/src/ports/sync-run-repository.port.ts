import type { ApiProblem, Result } from '@soopa/ui';
import type { SyncRun, TriggerSyncRunInput } from '../domain/sync-run';

export interface SyncRunRepositoryPort {
  listSyncRuns(
    tenantId: string,
    connectionId: string,
    limit?: number,
    signal?: AbortSignal,
  ): Promise<Result<readonly SyncRun[], ApiProblem>>;

  getSyncRun(
    tenantId: string,
    connectionId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<Result<SyncRun, ApiProblem>>;

  triggerSyncRun(
    tenantId: string,
    connectionId: string,
    input: TriggerSyncRunInput,
  ): Promise<Result<SyncRun, ApiProblem>>;
}
