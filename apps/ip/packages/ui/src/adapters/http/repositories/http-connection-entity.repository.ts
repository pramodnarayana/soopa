import {
  type ApiProblem,
  err,
  type FrontendLoggerPort,
  type HttpClientPort,
  ok,
  type Result,
} from '@soopa/ui';
import type {
  AddConnectionEntityInput,
  ConnectionEntity,
  UpdateConnectionEntityInput,
} from '../../../domain/connection-entity';
import type { ConnectionEntityRepositoryPort } from '../../../ports/connection-entity-repository.port';
import {
  mapAddConnectionEntityToWire,
  mapConnectionEntityFromWire,
  mapUpdateConnectionEntityToWire,
} from '../mappers/connection-entity.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  ConnectionEntityListWireSchema,
  ConnectionEntityWireSchema,
} from '../schemas/connection-entity.schema';

export class HttpConnectionEntityRepository implements ConnectionEntityRepositoryPort {
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
  ): Promise<Result<readonly ConnectionEntity[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/entities`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      ConnectionEntityListWireSchema,
      (items) => items.map(mapConnectionEntityFromWire),
      `GET /ip/connections/${connectionId}/entities`,
      this.logger,
    );
  }

  public async addEntity(
    tenantId: string,
    connectionId: string,
    input: AddConnectionEntityInput,
  ): Promise<Result<ConnectionEntity, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/entities`,
      mapAddConnectionEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      ConnectionEntityWireSchema,
      mapConnectionEntityFromWire,
      `POST /ip/connections/${connectionId}/entities`,
      this.logger,
    );
  }

  public async updateEntity(
    tenantId: string,
    connectionId: string,
    streamName: string,
    input: UpdateConnectionEntityInput,
  ): Promise<Result<ConnectionEntity, ApiProblem>> {
    const raw = await this.httpClient.patch<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/entities/${encodeURIComponent(streamName)}`,
      mapUpdateConnectionEntityToWire(input),
    );
    return parseAndMapResult(
      raw,
      ConnectionEntityWireSchema,
      mapConnectionEntityFromWire,
      `PATCH /ip/connections/${connectionId}/entities/${streamName}`,
      this.logger,
    );
  }

  public async removeEntity(
    tenantId: string,
    connectionId: string,
    streamName: string,
  ): Promise<Result<void, ApiProblem>> {
    const raw = await this.httpClient.delete<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/entities/${encodeURIComponent(streamName)}`,
    );
    if (!raw.ok) {
      return err(raw.error);
    }
    return ok(undefined);
  }

  public async resetCheckpoint(
    tenantId: string,
    connectionId: string,
    streamName: string,
  ): Promise<Result<ConnectionEntity, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/entities/${encodeURIComponent(streamName)}/reset-checkpoint`,
    );
    return parseAndMapResult(
      raw,
      ConnectionEntityWireSchema,
      mapConnectionEntityFromWire,
      `POST /ip/connections/${connectionId}/entities/${streamName}/reset-checkpoint`,
      this.logger,
    );
  }
}
