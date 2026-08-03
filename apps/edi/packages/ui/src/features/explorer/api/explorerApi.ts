import { useQuery } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import type { ExplorerEdiJson, ExplorerEdiMessage, ExplorerResponse, FilterRule } from '../types';

export const explorerKeys = {
  all: (tenantId: string) => ['explorer', tenantId] as const,
  messages: (tenantId: string, filters: FilterRule[]) =>
    [...explorerKeys.all(tenantId), 'messages', filters] as const,
  json: (tenantId: string, filters: FilterRule[]) =>
    [...explorerKeys.all(tenantId), 'json', filters] as const,
};

export function useExplorerQuery<T>(
  queryKeyArray: readonly unknown[],
  url: string,
  filters: FilterRule[],
  limit: number,
  offset: number,
  enabledOverride: boolean = true,
) {
  const api = useEdiNetwork();

  return useQuery({
    queryKey: [...queryKeyArray, limit, offset],
    queryFn: async () => {
      const response = await api.post<ExplorerResponse<T>>(
        url,
        { filters },
        { params: { limit, offset } },
      );
      return response.data;
    },
    enabled: enabledOverride,
    refetchInterval: 2000,
  });
}

export function useExplorerEdiMessages(
  filters: FilterRule[],
  limit: number = 100,
  offset: number = 0,
  enabled: boolean = true,
) {
  const tenantId = useTenantId();
  return useExplorerQuery<ExplorerEdiMessage>(
    explorerKeys.messages(tenantId, filters),
    'explorer/edi-messages',
    filters,
    limit,
    offset,
    enabled,
  );
}

export function useExplorerEdiJson(
  filters: FilterRule[],
  limit: number = 100,
  offset: number = 0,
  enabled: boolean = true,
) {
  const tenantId = useTenantId();
  return useExplorerQuery<ExplorerEdiJson>(
    explorerKeys.json(tenantId, filters),
    'explorer/edi-json',
    filters,
    limit,
    offset,
    enabled,
  );
}
