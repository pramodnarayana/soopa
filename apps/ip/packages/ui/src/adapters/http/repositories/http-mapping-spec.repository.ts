import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  ListMappingSpecsFilter,
  MappingSpec,
  SaveMappingSpecInput,
} from '../../../domain/mapping-spec';
import type { MappingSpecRepositoryPort } from '../../../ports/mapping-spec-repository.port';
import { mapMappingSpecFromWire, mapSaveMappingSpecToWire } from '../mappers/mapping-spec.mapper';
import { parseAndMapResult } from '../parse-wire';
import { MappingSpecListWireSchema, MappingSpecWireSchema } from '../schemas/mapping-spec.schema';

export class HttpMappingSpecRepository implements MappingSpecRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async saveMappingSpec(
    tenantId: string,
    input: SaveMappingSpecInput,
    signal?: AbortSignal,
  ): Promise<Result<MappingSpec, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/mapping-specs`,
      mapSaveMappingSpecToWire(input),
      { signal },
    );
    return parseAndMapResult(
      raw,
      MappingSpecWireSchema,
      mapMappingSpecFromWire,
      'POST /ip/mapping-specs',
      this.logger,
    );
  }

  public async getMappingSpec(
    tenantId: string,
    mappingSpecId: string,
    signal?: AbortSignal,
  ): Promise<Result<MappingSpec, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/mapping-specs/${encodeURIComponent(mappingSpecId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      MappingSpecWireSchema,
      mapMappingSpecFromWire,
      'GET /ip/mapping-specs/:id',
      this.logger,
    );
  }

  public async listMappingSpecs(
    tenantId: string,
    filter?: ListMappingSpecsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly MappingSpec[], ApiProblem>> {
    const params = new URLSearchParams();
    if (filter?.sourceType) {
      params.set('source_type', filter.sourceType);
    }
    if (filter?.targetConnectionId) {
      params.set('target_connection_id', filter.targetConnectionId);
    }
    const query = params.toString() ? `?${params.toString()}` : '';

    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/mapping-specs${query}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      MappingSpecListWireSchema,
      (list) => list.map(mapMappingSpecFromWire),
      'GET /ip/mapping-specs',
      this.logger,
    );
  }

  public async deleteMappingSpec(
    tenantId: string,
    mappingSpecId: string,
  ): Promise<Result<void, ApiProblem>> {
    const raw = await this.httpClient.delete<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/mapping-specs/${encodeURIComponent(mappingSpecId)}`,
    );
    if (!raw.ok) {
      return raw;
    }
    return { ok: true, value: undefined };
  }
}
