import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { StitchRunStatus } from '../domain/enums';
import type {
  ListStitchRunsFilter,
  RegisterStitchInput,
  Stitch,
  StitchDefinition,
  StitchRun,
  TriggerStitchEventInput,
} from '../domain/stitch';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

const ACTIVE_STITCH_RUN_POLL_MS = 2_000;

function isNonTerminalRunStatus(status: string): boolean {
  return (
    status === StitchRunStatus.PENDING ||
    status === StitchRunStatus.RUNNING ||
    status === StitchRunStatus.WAITING
  );
}

export function useStitchDefinitionsQuery(): IpQueryView<readonly StitchDefinition[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.stitches.definitions(tenantId),
    queryFn: ({ signal }) => repositories.stitches.listDefinitions(tenantId, signal),
    enabled: Boolean(tenantId),
    staleTime: 60_000,
  });
  return projectResultQuery(query);
}

export function useStitchDefinitionQuery(
  workflowId: string,
  version?: number,
): IpQueryView<StitchDefinition> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.stitches.definition(tenantId, workflowId, version),
    queryFn: ({ signal }) =>
      repositories.stitches.getDefinition(tenantId, workflowId, version, signal),
    enabled: Boolean(tenantId && workflowId),
  });
  return projectResultQuery(query);
}

export function useStitchesQuery(): IpQueryView<readonly Stitch[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.stitches.list(tenantId),
    queryFn: ({ signal }) => repositories.stitches.listStitches(tenantId, signal),
    enabled: Boolean(tenantId),
  });
  return projectResultQuery(query);
}

export function useStitchRunsQuery(
  filter?: ListStitchRunsFilter,
): IpQueryView<readonly StitchRun[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.stitches.runs(tenantId, filter),
    queryFn: ({ signal }) => repositories.stitches.listRuns(tenantId, filter, signal),
    enabled: Boolean(tenantId),
    refetchInterval: (q) => {
      const res = q.state.data;
      return res && res.ok && res.value.some((run) => isNonTerminalRunStatus(run.status))
        ? ACTIVE_STITCH_RUN_POLL_MS
        : false;
    },
  });
  return projectResultQuery(query);
}

export function useStitchRunQuery(runId: string): IpQueryView<StitchRun> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.stitches.run(tenantId, runId),
    queryFn: ({ signal }) => repositories.stitches.getRun(tenantId, runId, signal),
    enabled: Boolean(tenantId && runId),
    refetchInterval: (q) => {
      const res = q.state.data;
      return res && res.ok && isNonTerminalRunStatus(res.value.status)
        ? ACTIVE_STITCH_RUN_POLL_MS
        : false;
    },
  });
  return projectResultQuery(query);
}

export function useRegisterStitchMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RegisterStitchInput) =>
      repositories.stitches.registerStitch(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_stitch.register', res, {
        workflow_id: variables.workflowId,
        canonical_event_type: variables.canonicalEventType,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.stitches.list(tenantId) });
      }
    },
  });
}

export function useDispatchStitchEventMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TriggerStitchEventInput) =>
      repositories.stitches.dispatchEvent(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_stitch.dispatch_event', res, {
        canonical_event_type: variables.canonicalEventType,
        correlation_id: variables.correlationId,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ['ip', 'tenant', tenantId, 'stitches', 'runs'],
        });
      }
    },
  });
}
