import { useQuery } from '@tanstack/react-query';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useCatalogAppsQuery(
  filter?: CatalogAppsFilter,
): IpQueryView<readonly CatalogAppSummary[]> {
  const { repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.catalog.apps(filter),
    queryFn: ({ signal }) => repositories.catalog.listApps(filter, signal),
    staleTime: 60_000,
  });
  return projectResultQuery(query);
}

export function useCatalogAppSpecQuery(appId: string | null): IpQueryView<AppSpec> {
  const { repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.catalog.spec(appId ?? ''),
    queryFn: ({ signal }) => repositories.catalog.getAppSpec(appId ?? '', signal),
    enabled: Boolean(appId && appId.trim().length > 0),
    staleTime: 120_000,
  });
  return projectResultQuery(query);
}
