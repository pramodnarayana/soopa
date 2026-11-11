import {
  type ApiProblem,
  err,
  type FrontendLoggerPort,
  type HttpClientPort,
  ok,
  type Result,
} from '@soopa/ui';
import type {
  CreateSimulatorEntityInput,
  SimulatorEntity,
  UpdateSimulatorEntityInput,
} from '../../../domain/simulator';
import type { SimulatorRepositoryPort } from '../../../ports/simulator-repository.port';
import {
  mapCreateSimulatorEntityToWire,
  mapSimulatorEntityFromWire,
  mapUpdateSimulatorEntityToWire,
} from '../mappers/simulator.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  SimulatorEntityListWireSchema,
  SimulatorEntityWireSchema,
} from '../schemas/simulator.schema';

export class HttpSimulatorRepository implements SimulatorRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listEntities(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorEntity[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/simulator/entities`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityListWireSchema,
      (items) => items.map(mapSimulatorEntityFromWire),
      `GET /ip/connections/${connectionId}/simulator/entities`,
      this.logger,
    );
  }

  public async createEntity(
    tenantId: string,
    connectionId: string,
    input: CreateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/simulator/entities`,
      mapCreateSimulatorEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityWireSchema,
      mapSimulatorEntityFromWire,
      `POST /ip/connections/${connectionId}/simulator/entities`,
      this.logger,
    );
  }

  public async updateEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
    input: UpdateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const raw = await this.httpClient.patch<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/simulator/entities/${encodeURIComponent(entityId)}`,
      mapUpdateSimulatorEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityWireSchema,
      mapSimulatorEntityFromWire,
      `PATCH /ip/connections/${connectionId}/simulator/entities/${entityId}`,
      this.logger,
    );
  }

  public async deleteEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
  ): Promise<Result<void, ApiProblem>> {
    const raw = await this.httpClient.delete<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/simulator/entities/${encodeURIComponent(entityId)}`,
    );
    if (!raw.ok) {
      return err(raw.error);
    }
    return ok(undefined);
  }
}
