import { useQuery } from '@tanstack/react-query';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useCatalogAppsQuery(
  filter?: CatalogAppsFilter,
): IpQueryView<readonly CatalogAppSummary[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.catalog.apps(tenantId, filter),
    queryFn: ({ signal }) => repositories.catalog.listApps(tenantId, filter, signal),
    enabled: Boolean(tenantId && tenantId.trim().length > 0),
    staleTime: 60_000,
  });
  return projectResultQuery(query);
}

export function useCatalogAppSpecQuery(appId: string | null): IpQueryView<AppSpec> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.catalog.spec(tenantId, appId ?? ''),
    queryFn: ({ signal }) => repositories.catalog.getAppSpec(tenantId, appId ?? '', signal),
    enabled: Boolean(tenantId && tenantId.trim().length > 0 && appId && appId.trim().length > 0),
    staleTime: 120_000,
  });
  return projectResultQuery(query);
}
