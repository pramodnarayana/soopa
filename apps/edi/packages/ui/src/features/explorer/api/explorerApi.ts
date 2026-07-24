import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { useAuth } from 'react-oidc-context';
import type { ExplorerEdiJson, ExplorerEdiMessage, ExplorerResponse, FilterRule } from '../types';

export const explorerKeys = {
  all: ['explorer'] as const,
  messages: (filters: FilterRule[]) => [...explorerKeys.all, 'messages', filters] as const,
  json: (filters: FilterRule[]) => [...explorerKeys.all, 'json', filters] as const,
};

export function useExplorerQuery<T>(
  queryKeyArray: readonly unknown[],
  url: string,
  filters: FilterRule[],
  limit: number,
  offset: number,
  enabledOverride: boolean = true,
) {
  const auth = useAuth();

  return useQuery({
    queryKey: [...queryKeyArray, limit, offset],
    queryFn: async () => {
      const response = await axios.post<ExplorerResponse<T>>(
        url,
        { filters },
        {
          params: { limit, offset },
          headers: { Authorization: `Bearer ${auth.user?.access_token}` },
        },
      );
      return response.data;
    },
    enabled: !!auth.user?.access_token && enabledOverride,
    refetchInterval: 2000,
  });
}

export function useExplorerEdiMessages(
  filters: FilterRule[],
  limit: number = 100,
  offset: number = 0,
  enabled: boolean = true,
) {
  return useExplorerQuery<ExplorerEdiMessage>(
    explorerKeys.messages(filters),
    '/api/v1/explorer/edi-messages',
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
  return useExplorerQuery<ExplorerEdiJson>(
    explorerKeys.json(filters),
    '/api/v1/explorer/edi-json',
    filters,
    limit,
    offset,
    enabled,
  );
}
