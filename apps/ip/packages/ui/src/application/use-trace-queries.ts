import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { JsonRecord, ReplayStageValue } from '../domain/enums';
import type { IpTrace, IpTraceLineageItem, ListRecentTracesFilter } from '../domain/trace';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useRecentTracesQuery(
  filter?: ListRecentTracesFilter,
  enabled = true,
): IpQueryView<readonly IpTraceLineageItem[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.traces.recent(tenantId, filter),
    queryFn: ({ signal }) => repositories.traces.listRecentTraces(tenantId, filter, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}

export function useSearchTracesByCorrelationQuery(
  correlationId: string,
  limit = 50,
): IpQueryView<readonly IpTraceLineageItem[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const trimmed = correlationId.trim();
  const query = useQuery({
    queryKey: ipQueryKeys.traces.search(tenantId, trimmed, limit),
    queryFn: ({ signal }) =>
      repositories.traces.searchByCorrelation(tenantId, trimmed, limit, signal),
    enabled: Boolean(tenantId && trimmed.length > 0),
  });
  return projectResultQuery(query);
}

export function useIpTraceQuery(traceId: string, hydratePayloads = true): IpQueryView<IpTrace> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.traces.detail(tenantId, traceId, hydratePayloads),
    queryFn: ({ signal }) =>
      repositories.traces.getTrace(tenantId, traceId, hydratePayloads, signal),
    enabled: Boolean(tenantId && traceId),
  });
  return projectResultQuery(query);
}

export function useIpTraceLineageQuery(
  traceId: string,
): IpQueryView<readonly IpTraceLineageItem[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.traces.lineage(tenantId, traceId),
    queryFn: ({ signal }) => repositories.traces.getTraceLineage(tenantId, traceId, signal),
    enabled: Boolean(tenantId && traceId),
  });
  return projectResultQuery(query);
}

export function useReplayTransactionMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { traceId: string; stage: ReplayStageValue }) =>
      repositories.traces.replayTransaction(tenantId, params.traceId, params.stage),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_trace.replay', res, {
        trace_id: variables.traceId,
        stage: variables.stage,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.traces.all(tenantId) });
      }
    },
  });
}

export function useModifyAndReplayMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      traceId: string;
      stage: ReplayStageValue;
      modifiedPayload: JsonRecord;
    }) =>
      repositories.traces.modifyAndReplayTransaction(
        tenantId,
        params.traceId,
        params.stage,
        params.modifiedPayload,
      ),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_trace.modify_and_replay', res, {
        trace_id: variables.traceId,
        stage: variables.stage,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.traces.all(tenantId) });
      }
    },
  });
}

export function useBulkReplayMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { traceIds: readonly string[]; stage: ReplayStageValue }) =>
      repositories.traces.bulkReplayTransactions(tenantId, params.traceIds, params.stage),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_trace.bulk_replay', res, {
        requested_count: variables.traceIds.length,
        stage: variables.stage,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.traces.all(tenantId) });
      }
    },
  });
}
