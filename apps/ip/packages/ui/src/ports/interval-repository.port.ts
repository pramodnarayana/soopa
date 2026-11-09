import type { ApiProblem, Result } from '@soopa/ui';
import type {
  BatchManifestSummary,
  BatchReconciliationOverview,
  DailyTouRollup,
  IntervalLineageTrace,
  IntervalWindowCompleteness,
} from '../domain/intervals';

export interface GetReconciliationParams {
  readonly connectionId?: string;
  readonly recentLimit?: number;
}

export interface GetCompletenessParams {
  readonly connectionId: string;
  readonly serviceDate: string;
  readonly streamName?: string;
}

export interface GetDailyTouRollupsParams {
  readonly serviceDate: string;
  readonly connectionId?: string;
  readonly feederId?: string;
  readonly sourceDeviceId?: string;
}

export interface IntervalRepositoryPort {
  getReconciliationOverview(
    tenantId: string,
    params?: GetReconciliationParams,
    signal?: AbortSignal,
  ): Promise<Result<BatchReconciliationOverview, ApiProblem>>;

  getDailyCompleteness(
    tenantId: string,
    params: GetCompletenessParams,
    signal?: AbortSignal,
  ): Promise<Result<readonly IntervalWindowCompleteness[], ApiProblem>>;

  getDailyTouRollups(
    tenantId: string,
    params: GetDailyTouRollupsParams,
    signal?: AbortSignal,
  ): Promise<Result<readonly DailyTouRollup[], ApiProblem>>;

  traceDeviceIntervals(
    tenantId: string,
    sourceDeviceId: string,
    serviceDate: string,
    signal?: AbortSignal,
  ): Promise<Result<IntervalLineageTrace, ApiProblem>>;

  recordSettlementReceipt(
    tenantId: string,
    batchId: string,
    deliveryReceiptId: string,
  ): Promise<Result<BatchManifestSummary, ApiProblem>>;
}
