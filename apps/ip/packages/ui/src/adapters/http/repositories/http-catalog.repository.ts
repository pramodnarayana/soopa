import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../../../domain/catalog';
import type { CatalogRepositoryPort } from '../../../ports/catalog-repository.port';
import { mapAppSpecFromWire, mapCatalogAppSummaryFromWire } from '../mappers/catalog.mapper';
import { parseAndMapResult } from '../parse-wire';
import { AppSpecWireSchema, CatalogAppSummaryListWireSchema } from '../schemas/catalog.schema';

export class HttpCatalogRepository implements CatalogRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listApps(
    filter?: CatalogAppsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly CatalogAppSummary[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>('/api/v1/ip/catalog/apps', {
      params: {
        category: filter?.category,
        search: filter?.search,
      },
      signal,
    });
    return parseAndMapResult(
      raw,
      CatalogAppSummaryListWireSchema,
      (items) => items.map(mapCatalogAppSummaryFromWire),
      'GET /api/v1/ip/catalog/apps',
      this.logger,
    );
  }

  public async getAppSpec(
    appId: string,
    signal?: AbortSignal,
  ): Promise<Result<AppSpec, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/ip/catalog/apps/${encodeURIComponent(appId)}/spec`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      AppSpecWireSchema,
      mapAppSpecFromWire,
      `GET /api/v1/ip/catalog/apps/${appId}/spec`,
      this.logger,
    );
  }
}
