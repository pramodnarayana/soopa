import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  ListStitchRunsFilter,
  RegisterStitchInput,
  Stitch,
  StitchDefinition,
  StitchRun,
  TriggerStitchEventInput,
  TriggerStitchEventResult,
} from '../../../domain/stitch';
import type { StitchRepositoryPort } from '../../../ports/stitch-repository.port';
import {
  mapRegisterStitchToWire,
  mapStitchDefinitionFromWire,
  mapStitchFromWire,
  mapStitchRunFromWire,
  mapTriggerStitchEventFromWire,
  mapTriggerStitchEventToWire,
} from '../mappers/stitch.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  StitchDefinitionListWireSchema,
  StitchDefinitionWireSchema,
  StitchListWireSchema,
  StitchRunListWireSchema,
  StitchRunWireSchema,
  StitchWireSchema,
  TriggerStitchEventWireSchema,
} from '../schemas/stitch.schema';

export class HttpStitchRepository implements StitchRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listDefinitions(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly StitchDefinition[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches/definitions`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      StitchDefinitionListWireSchema,
      (items) => items.map(mapStitchDefinitionFromWire),
      'GET /ip/stitches/definitions',
      this.logger,
    );
  }

  public async getDefinition(
    tenantId: string,
    workflowId: string,
    version?: number,
    signal?: AbortSignal,
  ): Promise<Result<StitchDefinition, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches/definitions/${encodeURIComponent(workflowId)}`,
      { params: { version }, signal },
    );
    return parseAndMapResult(
      raw,
      StitchDefinitionWireSchema,
      mapStitchDefinitionFromWire,
      `GET /ip/stitches/definitions/${workflowId}`,
      this.logger,
    );
  }

  public async listStitches(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Stitch[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      StitchListWireSchema,
      (items) => items.map(mapStitchFromWire),
      'GET /ip/stitches',
      this.logger,
    );
  }

  public async registerStitch(
    tenantId: string,
    input: RegisterStitchInput,
  ): Promise<Result<Stitch, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches`,
      mapRegisterStitchToWire(input),
    );
    return parseAndMapResult(
      raw,
      StitchWireSchema,
      mapStitchFromWire,
      'POST /ip/stitches',
      this.logger,
    );
  }

  public async dispatchEvent(
    tenantId: string,
    input: TriggerStitchEventInput,
  ): Promise<Result<TriggerStitchEventResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches/dispatch`,
      mapTriggerStitchEventToWire(input),
    );
    return parseAndMapResult(
      raw,
      TriggerStitchEventWireSchema,
      mapTriggerStitchEventFromWire,
      'POST /ip/stitches/dispatch',
      this.logger,
    );
  }

  public async listRuns(
    tenantId: string,
    filter?: ListStitchRunsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly StitchRun[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches/runs`,
      {
        params: {
          workflow_id: filter?.workflowId,
          status: filter?.status,
          limit: filter?.limit ?? 50,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      StitchRunListWireSchema,
      (items) => items.map(mapStitchRunFromWire),
      'GET /ip/stitches/runs',
      this.logger,
    );
  }

  public async getRun(
    tenantId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<Result<StitchRun, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/stitches/runs/${encodeURIComponent(runId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      StitchRunWireSchema,
      mapStitchRunFromWire,
      `GET /ip/stitches/runs/${runId}`,
      this.logger,
    );
  }
}
