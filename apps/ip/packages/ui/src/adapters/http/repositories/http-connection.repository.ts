import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  CheckConnectionInput,
  Connection,
  ConnectionCheckResult,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
} from '../../../domain/connection';
import type { ConnectionRepositoryPort } from '../../../ports/connection-repository.port';
import {
  mapCheckConnectionToWire,
  mapConnectionCheckFromWire,
  mapConnectionFromWire,
  mapCreateConnectionToWire,
  mapDiscoveredCatalogFromWire,
  mapRelinkConnectionToWire,
} from '../mappers/connection.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  ConnectionCheckWireSchema,
  ConnectionListWireSchema,
  ConnectionWireSchema,
  DiscoveredCatalogWireSchema,
} from '../schemas/connection.schema';

export class HttpConnectionRepository implements ConnectionRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listConnections(
    tenantId: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Connection[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections`,
      { params: { status }, signal },
    );
    return parseAndMapResult(
      raw,
      ConnectionListWireSchema,
      (items) => items.map(mapConnectionFromWire),
      'GET /ip/connections',
      this.logger,
    );
  }

  public async getConnection(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<Connection, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      ConnectionWireSchema,
      mapConnectionFromWire,
      `GET /ip/connections/${connectionId}`,
      this.logger,
    );
  }

  public async checkConnection(
    tenantId: string,
    input: CheckConnectionInput,
    signal?: AbortSignal,
  ): Promise<Result<ConnectionCheckResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/check`,
      mapCheckConnectionToWire(input),
      { signal },
    );
    return parseAndMapResult(
      raw,
      ConnectionCheckWireSchema,
      mapConnectionCheckFromWire,
      'POST /ip/connections/check',
      this.logger,
    );
  }

  public async createConnection(
    tenantId: string,
    input: CreateConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections`,
      mapCreateConnectionToWire(input),
    );
    return parseAndMapResult(
      raw,
      ConnectionWireSchema,
      mapConnectionFromWire,
      'POST /ip/connections',
      this.logger,
    );
  }

  public async discoverCatalog(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<DiscoveredCatalog, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/discover`,
    );
    return parseAndMapResult(
      raw,
      DiscoveredCatalogWireSchema,
      mapDiscoveredCatalogFromWire,
      `POST /ip/connections/${connectionId}/discover`,
      this.logger,
    );
  }

  public async relinkConnection(
    tenantId: string,
    connectionId: string,
    input: RelinkConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}/relink`,
      mapRelinkConnectionToWire(input),
    );
    return parseAndMapResult(
      raw,
      ConnectionWireSchema,
      mapConnectionFromWire,
      `POST /ip/connections/${connectionId}/relink`,
      this.logger,
    );
  }

  public async deactivateConnection(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<Connection, ApiProblem>> {
    const raw = await this.httpClient.delete<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/connections/${encodeURIComponent(connectionId)}`,
    );
    return parseAndMapResult(
      raw,
      ConnectionWireSchema,
      mapConnectionFromWire,
      `DELETE /ip/connections/${connectionId}`,
      this.logger,
    );
  }
}
