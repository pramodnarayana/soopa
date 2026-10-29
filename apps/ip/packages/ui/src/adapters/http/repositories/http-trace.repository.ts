import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type { JsonRecord, ReplayStageValue } from '../../../domain/enums';
import type {
  BulkReplayResult,
  IpTrace,
  IpTraceLineageItem,
  ListRecentTracesFilter,
  ReplayTransactionResult,
} from '../../../domain/trace';
import type { TraceRepositoryPort } from '../../../ports/trace-repository.port';
import {
  mapBulkReplayResultFromWire,
  mapIpTraceFromWire,
  mapLineageItemFromWire,
  mapReplayResultFromWire,
} from '../mappers/trace.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  BulkReplayResultWireSchema,
  IpTraceLineageListWireSchema,
  IpTraceWireSchema,
  ReplayTransactionResultWireSchema,
} from '../schemas/trace.schema';

export class HttpTraceRepository implements TraceRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listRecentTraces(
    tenantId: string,
    filter?: ListRecentTracesFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions`,
      {
        params: {
          status: filter?.status,
          min_replay_count: filter?.minReplayCount,
          limit: filter?.limit ?? 50,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      IpTraceLineageListWireSchema,
      (items) => items.map(mapLineageItemFromWire),
      'GET /ip/transactions',
      this.logger,
    );
  }

  public async searchByCorrelation(
    tenantId: string,
    correlationId: string,
    limit = 50,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/search`,
      {
        params: {
          correlation_id: correlationId,
          limit,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      IpTraceLineageListWireSchema,
      (items) => items.map(mapLineageItemFromWire),
      'GET /ip/transactions/search',
      this.logger,
    );
  }

  public async getTrace(
    tenantId: string,
    traceId: string,
    hydratePayloads = true,
    signal?: AbortSignal,
  ): Promise<Result<IpTrace, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/${encodeURIComponent(traceId)}`,
      {
        params: { hydrate_payloads: hydratePayloads },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      IpTraceWireSchema,
      mapIpTraceFromWire,
      `GET /ip/transactions/${traceId}`,
      this.logger,
    );
  }

  public async getTraceLineage(
    tenantId: string,
    traceId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/${encodeURIComponent(traceId)}/lineage`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      IpTraceLineageListWireSchema,
      (items) => items.map(mapLineageItemFromWire),
      `GET /ip/transactions/${traceId}/lineage`,
      this.logger,
    );
  }

  public async replayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/${encodeURIComponent(traceId)}/replay`,
      { stage },
    );
    return parseAndMapResult(
      raw,
      ReplayTransactionResultWireSchema,
      mapReplayResultFromWire,
      `POST /ip/transactions/${traceId}/replay`,
      this.logger,
    );
  }

  public async modifyAndReplayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
    modifiedPayload: JsonRecord,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/${encodeURIComponent(traceId)}/modify-and-replay`,
      {
        stage,
        modified_payload: modifiedPayload,
      },
    );
    return parseAndMapResult(
      raw,
      ReplayTransactionResultWireSchema,
      mapReplayResultFromWire,
      `POST /ip/transactions/${traceId}/modify-and-replay`,
      this.logger,
    );
  }

  public async bulkReplayTransactions(
    tenantId: string,
    traceIds: readonly string[],
    stage: ReplayStageValue,
  ): Promise<Result<BulkReplayResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transactions/bulk-replay`,
      {
        trace_ids: traceIds,
        stage,
      },
    );
    return parseAndMapResult(
      raw,
      BulkReplayResultWireSchema,
      mapBulkReplayResultFromWire,
      'POST /ip/transactions/bulk-replay',
      this.logger,
    );
  }
}
