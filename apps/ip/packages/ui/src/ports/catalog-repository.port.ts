import type { ApiProblem, Result } from '@soopa/ui';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';

export interface CatalogRepositoryPort {
  listApps(
    filter?: CatalogAppsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly CatalogAppSummary[], ApiProblem>>;

  getAppSpec(appId: string, signal?: AbortSignal): Promise<Result<AppSpec, ApiProblem>>;
}
