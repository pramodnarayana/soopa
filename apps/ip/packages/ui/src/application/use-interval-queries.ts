import type { ApiProblem, Result } from '@soopa/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  BatchManifestSummary,
  BatchReconciliationOverview,
  DailyTouRollup,
  IntervalLineageTrace,
  IntervalWindowCompleteness,
} from '../domain/intervals';
import type {
  GetCompletenessParams,
  GetDailyTouRollupsParams,
  GetReconciliationParams,
} from '../ports/interval-repository.port';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useIntervalReconciliationQuery(
  params?: GetReconciliationParams,
  enabled = true,
): IpQueryView<BatchReconciliationOverview> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.intervals.reconciliation(tenantId, params),
    queryFn: ({ signal }) =>
      repositories.intervals.getReconciliationOverview(tenantId, params, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}

export function useDailyCompletenessQuery(
  params: GetCompletenessParams,
  enabled = true,
): IpQueryView<readonly IntervalWindowCompleteness[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.intervals.completeness(tenantId, params),
    queryFn: ({ signal }) => repositories.intervals.getDailyCompleteness(tenantId, params, signal),
    enabled:
      Boolean(tenantId) && Boolean(params.connectionId) && Boolean(params.serviceDate) && enabled,
  });
  return projectResultQuery(query);
}

export function useDailyTouRollupsQuery(
  params: GetDailyTouRollupsParams,
  enabled = true,
): IpQueryView<readonly DailyTouRollup[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.intervals.touRollups(tenantId, params),
    queryFn: ({ signal }) => repositories.intervals.getDailyTouRollups(tenantId, params, signal),
    enabled: Boolean(tenantId) && Boolean(params.serviceDate) && enabled,
  });
  return projectResultQuery(query);
}

export function useDeviceIntervalLineageQuery(
  sourceDeviceId: string | null,
  serviceDate: string,
): IpQueryView<IntervalLineageTrace> {
  const { tenantId, repositories } = useIpWorkspace();
  const resolvedDeviceId = sourceDeviceId ?? '';
  const query = useQuery({
    queryKey: ipQueryKeys.intervals.deviceLineage(tenantId, resolvedDeviceId, serviceDate),
    queryFn: ({ signal }) =>
      repositories.intervals.traceDeviceIntervals(tenantId, resolvedDeviceId, serviceDate, signal),
    enabled: Boolean(tenantId) && Boolean(sourceDeviceId) && Boolean(serviceDate),
  });
  return projectResultQuery(query);
}

export interface RecordSettlementReceiptVariables {
  readonly batchId: string;
  readonly deliveryReceiptId: string;
}

export function useRecordSettlementReceiptMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();

  return useMutation<
    Result<BatchManifestSummary, ApiProblem>,
    Error,
    RecordSettlementReceiptVariables
  >({
    mutationFn: async ({ batchId, deliveryReceiptId }) => {
      logger.info('ip_interval_receipt.started', {
        batch_id: batchId,
        delivery_receipt_id: deliveryReceiptId,
      });
      const res = await repositories.intervals.recordSettlementReceipt(
        tenantId,
        batchId,
        deliveryReceiptId,
      );
      logResultOutcome(logger, 'ip_interval_receipt', res, {
        batch_id: batchId,
        delivery_receipt_id: deliveryReceiptId,
      });
      return res;
    },
    onSuccess: (res) => {
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.intervals.all(tenantId),
        });
      }
    },
  });
}
