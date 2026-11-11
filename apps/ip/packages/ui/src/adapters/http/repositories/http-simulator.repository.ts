import {
  type ApiProblem,
  err,
  type FrontendLoggerPort,
  type HttpClientPort,
  ok,
  type Result,
} from '@soopa/ui';
import type {
  CreatedSimulatorSandbox,
  CreateSimulatorEntityInput,
  CreateSimulatorSandboxInput,
  SimulatorEntity,
  SimulatorSandbox,
  UpdateSimulatorEntityInput,
} from '../../../domain/simulator';
import type { SimulatorRepositoryPort } from '../../../ports/simulator-repository.port';
import {
  mapCreatedSimulatorSandboxFromWire,
  mapCreateSimulatorEntityToWire,
  mapCreateSimulatorSandboxToWire,
  mapSimulatorEntityFromWire,
  mapSimulatorSandboxFromWire,
  mapUpdateSimulatorEntityToWire,
} from '../mappers/simulator.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  CreatedSimulatorSandboxWireSchema,
  SimulatorEntityListWireSchema,
  SimulatorEntityWireSchema,
  SimulatorSandboxListWireSchema,
  SimulatorSandboxWireSchema,
} from '../schemas/simulator.schema';

export class HttpSimulatorRepository implements SimulatorRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async createSandbox(
    tenantId: string,
    input: CreateSimulatorSandboxInput,
  ): Promise<Result<CreatedSimulatorSandbox, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes`,
      mapCreateSimulatorSandboxToWire(input),
    );
    return parseAndMapResult(
      raw,
      CreatedSimulatorSandboxWireSchema,
      mapCreatedSimulatorSandboxFromWire,
      'POST /ip/simulator/sandboxes',
      this.logger,
    );
  }

  public async listSandboxes(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorSandbox[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      SimulatorSandboxListWireSchema,
      (items) => items.map(mapSimulatorSandboxFromWire),
      'GET /ip/simulator/sandboxes',
      this.logger,
    );
  }

  public async getSandbox(
    tenantId: string,
    sandboxId: string,
    signal?: AbortSignal,
  ): Promise<Result<SimulatorSandbox, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      SimulatorSandboxWireSchema,
      mapSimulatorSandboxFromWire,
      `GET /ip/simulator/sandboxes/${sandboxId}`,
      this.logger,
    );
  }

  public async deleteSandbox(
    tenantId: string,
    sandboxId: string,
  ): Promise<Result<void, ApiProblem>> {
    const raw = await this.httpClient.delete<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}`,
    );
    if (!raw.ok) {
      return err(raw.error);
    }
    return ok(undefined);
  }

  public async listEntities(
    tenantId: string,
    sandboxId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorEntity[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}/entities`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityListWireSchema,
      (items) => items.map(mapSimulatorEntityFromWire),
      `GET /ip/simulator/sandboxes/${sandboxId}/entities`,
      this.logger,
    );
  }

  public async createEntity(
    tenantId: string,
    sandboxId: string,
    input: CreateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}/entities`,
      mapCreateSimulatorEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityWireSchema,
      mapSimulatorEntityFromWire,
      `POST /ip/simulator/sandboxes/${sandboxId}/entities`,
      this.logger,
    );
  }

  public async updateEntity(
    tenantId: string,
    sandboxId: string,
    entityId: string,
    input: UpdateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const raw = await this.httpClient.patch<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}/entities/${encodeURIComponent(entityId)}`,
      mapUpdateSimulatorEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      SimulatorEntityWireSchema,
      mapSimulatorEntityFromWire,
      `PATCH /ip/simulator/sandboxes/${sandboxId}/entities/${entityId}`,
      this.logger,
    );
  }

  public async deleteEntity(
    tenantId: string,
    sandboxId: string,
    entityId: string,
  ): Promise<Result<void, ApiProblem>> {
    const raw = await this.httpClient.delete<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/simulator/sandboxes/${encodeURIComponent(sandboxId)}/entities/${encodeURIComponent(entityId)}`,
    );
    if (!raw.ok) {
      return err(raw.error);
    }
    return ok(undefined);
  }
}
