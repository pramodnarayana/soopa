import type { ApiProblem, Result } from '@soopa/ui';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';

export interface CatalogRepositoryPort {
  listApps(
    tenantId: string,
    filter?: CatalogAppsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly CatalogAppSummary[], ApiProblem>>;

  getAppSpec(
    tenantId: string,
    appId: string,
    signal?: AbortSignal,
  ): Promise<Result<AppSpec, ApiProblem>>;
}
