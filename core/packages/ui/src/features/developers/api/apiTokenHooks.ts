import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { CreateApiTokenPayload } from '../types';
import { HttpApiTokenRepository } from './apiTokenRepository';

export interface ApiTokenHookConfig {
  baseUrl: string;
  tenantId: string;
  token: string;
}

const apiTokenKeys = {
  all: (tenantId: string) => ['platform', 'api-tokens', tenantId] as const,
};

function useApiTokenRepo({ baseUrl, tenantId, token }: ApiTokenHookConfig) {
  return new HttpApiTokenRepository(baseUrl, tenantId, token);
}

export function useApiTokensQuery(config: ApiTokenHookConfig) {
  const repo = useApiTokenRepo(config);
  return useQuery({
    queryKey: apiTokenKeys.all(config.tenantId),
    queryFn: () => repo.getAll(),
    enabled: !!config.token && !!config.tenantId,
  });
}

export function useCreateApiTokenMutation(config: ApiTokenHookConfig) {
  const repo = useApiTokenRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateApiTokenPayload) => repo.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
    },
  });
}

export function useUpdateApiTokenMutation(config: ApiTokenHookConfig) {
  const repo = useApiTokenRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; active?: boolean } }) =>
      repo.update(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
    },
  });
}

export function useDeleteApiTokenMutation(config: ApiTokenHookConfig) {
  const repo = useApiTokenRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repo.delete(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
    },
  });
}
