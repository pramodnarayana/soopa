import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type { SyncRun, TriggerSyncRunInput } from '../../../domain/sync-run';
import type { SyncRunRepositoryPort } from '../../../ports/sync-run-repository.port';
import { mapSyncRunFromWire, mapTriggerSyncRunToWire } from '../mappers/sync-run.mapper';
import { parseAndMapResult } from '../parse-wire';
import { SyncRunListWireSchema, SyncRunWireSchema } from '../schemas/sync-run.schema';

export class HttpSyncRunRepository implements SyncRunRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listSyncRuns(
    tenantId: string,
    connectionId: string,
    limit = 50,
    signal?: AbortSignal,
  ): Promise<Result<readonly SyncRun[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/sync-runs`,
      { params: { limit }, signal },
    );
    return parseAndMapResult(
      raw,
      SyncRunListWireSchema,
      (items) => items.map(mapSyncRunFromWire),
      `GET /ip/connections/${connectionId}/sync-runs`,
      this.logger,
    );
  }

  public async getSyncRun(
    tenantId: string,
    connectionId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<Result<SyncRun, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/sync-runs/${encodeURIComponent(runId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      SyncRunWireSchema,
      mapSyncRunFromWire,
      `GET /ip/connections/${connectionId}/sync-runs/${runId}`,
      this.logger,
    );
  }

  public async triggerSyncRun(
    tenantId: string,
    connectionId: string,
    input: TriggerSyncRunInput,
  ): Promise<Result<SyncRun, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/sync-runs`,
      mapTriggerSyncRunToWire(input),
    );
    return parseAndMapResult(
      raw,
      SyncRunWireSchema,
      mapSyncRunFromWire,
      `POST /ip/connections/${connectionId}/sync-runs`,
      this.logger,
    );
  }
}
