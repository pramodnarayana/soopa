import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { SyncRunStatus } from '../domain/enums';
import type { SyncRun, TriggerSyncRunInput } from '../domain/sync-run';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

const ACTIVE_SYNC_POLL_MS = 2_500;

function hasActiveSyncRuns(runs: readonly SyncRun[]): boolean {
  return runs.some(
    (run) => run.status === SyncRunStatus.QUEUED || run.status === SyncRunStatus.RUNNING,
  );
}

export function useSyncRunsQuery(
  connectionId: string,
  limit = 50,
): IpQueryView<readonly SyncRun[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.syncRuns.list(tenantId, connectionId, limit),
    queryFn: ({ signal }) =>
      repositories.syncRuns.listSyncRuns(tenantId, connectionId, limit, signal),
    enabled: Boolean(tenantId && connectionId),
    refetchInterval: (q) => {
      const res = q.state.data;
      return res && res.ok && hasActiveSyncRuns(res.value) ? ACTIVE_SYNC_POLL_MS : false;
    },
  });
  return projectResultQuery(query);
}

export function useTriggerSyncRunMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TriggerSyncRunInput) =>
      repositories.syncRuns.triggerSyncRun(tenantId, connectionId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_sync_run.trigger', res, {
        connection_id: connectionId,
        stream_name: variables.streamName,
        forced_kind: variables.forcedKind,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.syncRuns.all(tenantId, connectionId),
        });
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
        });
      }
    },
  });
}
