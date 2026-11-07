import type { ApiProblem, Result } from '@soopa/ui';
import type { JsonRecord, ReplayStageValue } from '../domain/enums';
import type {
  BulkReplayResult,
  IpTrace,
  IpTraceLineageItem,
  ListRecentTracesFilter,
  ReplayTransactionResult,
} from '../domain/trace';

export interface TraceRepositoryPort {
  listRecentTraces(
    tenantId: string,
    filter?: ListRecentTracesFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>>;

  searchByCorrelation(
    tenantId: string,
    correlationId: string,
    limit?: number,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>>;

  getTrace(
    tenantId: string,
    traceId: string,
    hydratePayloads?: boolean,
    signal?: AbortSignal,
  ): Promise<Result<IpTrace, ApiProblem>>;

  getTraceLineage(
    tenantId: string,
    traceId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>>;

  replayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>>;

  modifyAndReplayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
    modifiedPayload: JsonRecord,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>>;

  bulkReplayTransactions(
    tenantId: string,
    traceIds: readonly string[],
    stage: ReplayStageValue,
  ): Promise<Result<BulkReplayResult, ApiProblem>>;
}
