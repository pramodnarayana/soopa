import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  BatchManifestSummary,
  BatchReconciliationOverview,
  DailyTouRollup,
  IntervalLineageTrace,
  IntervalWindowCompleteness,
} from '../../../domain/intervals';
import type {
  GetCompletenessParams,
  GetDailyTouRollupsParams,
  GetReconciliationParams,
  IntervalRepositoryPort,
} from '../../../ports/interval-repository.port';
import {
  mapBatchManifestFromWire,
  mapCompletenessFromWire,
  mapDailyTouRollupFromWire,
  mapIntervalLineageTraceFromWire,
  mapReconciliationOverviewFromWire,
} from '../mappers/interval.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  BatchManifestSummaryWireSchema,
  BatchReconciliationOverviewWireSchema,
  DailyTouRollupListWireSchema,
  IntervalLineageTraceWireSchema,
  IntervalWindowCompletenessListWireSchema,
} from '../schemas/interval.schema';

export class HttpIntervalRepository implements IntervalRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async getReconciliationOverview(
    tenantId: string,
    params?: GetReconciliationParams,
    signal?: AbortSignal,
  ): Promise<Result<BatchReconciliationOverview, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/intervals/reconciliation`,
      {
        params: {
          connection_id: params?.connectionId,
          recent_limit: params?.recentLimit ?? 20,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      BatchReconciliationOverviewWireSchema,
      mapReconciliationOverviewFromWire,
      'GET /ip/intervals/reconciliation',
      this.logger,
    );
  }

  public async getDailyCompleteness(
    tenantId: string,
    params: GetCompletenessParams,
    signal?: AbortSignal,
  ): Promise<Result<readonly IntervalWindowCompleteness[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/intervals/completeness/${encodeURIComponent(params.connectionId)}`,
      {
        params: {
          service_date: params.serviceDate,
          stream: params.streamName,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      IntervalWindowCompletenessListWireSchema,
      (items) => items.map(mapCompletenessFromWire),
      'GET /ip/intervals/completeness/:connectionId',
      this.logger,
    );
  }

  public async getDailyTouRollups(
    tenantId: string,
    params: GetDailyTouRollupsParams,
    signal?: AbortSignal,
  ): Promise<Result<readonly DailyTouRollup[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/intervals/tou-rollups`,
      {
        params: {
          service_date: params.serviceDate,
          feeder_id: params.feederId,
          source_meter_id: params.sourceDeviceId,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      DailyTouRollupListWireSchema,
      (items) => items.map(mapDailyTouRollupFromWire),
      'GET /ip/intervals/tou-rollups',
      this.logger,
    );
  }

  public async traceDeviceIntervals(
    tenantId: string,
    sourceDeviceId: string,
    serviceDate: string,
    signal?: AbortSignal,
  ): Promise<Result<IntervalLineageTrace, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/intervals/devices/${encodeURIComponent(sourceDeviceId)}/trace`,
      {
        params: {
          service_date: serviceDate,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      IntervalLineageTraceWireSchema,
      mapIntervalLineageTraceFromWire,
      'GET /ip/intervals/devices/:sourceDeviceId/trace',
      this.logger,
    );
  }

  public async recordSettlementReceipt(
    tenantId: string,
    batchId: string,
    deliveryReceiptId: string,
  ): Promise<Result<BatchManifestSummary, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/intervals/batches/${encodeURIComponent(batchId)}/receipt`,
      {
        delivery_receipt_id: deliveryReceiptId,
      },
    );
    return parseAndMapResult(
      raw,
      BatchManifestSummaryWireSchema,
      mapBatchManifestFromWire,
      'POST /ip/intervals/batches/:batchId/receipt',
      this.logger,
    );
  }
}
