import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { useToastMutation } from '@/hooks/use-toast-mutation';
import type { CreateApiTokenPayload } from '../types';
import { createApiTokenRepository } from './apiTokensApi';

export const apiTokenKeys = {
  all: ['apiTokens'] as const,
  lists: (tenantId: string) => [...apiTokenKeys.all, tenantId] as const,
};

function useRepository(tenantId: string) {
  const auth = useAuth();
  return createApiTokenRepository(
    auth.user?.access_token ?? '',
    tenantId,
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
      'http://localhost:3000',
  );
}

export function useApiTokensQuery(tenantId: string) {
  const repo = useRepository(tenantId);
  const auth = useAuth();
  return useQuery({
    queryKey: apiTokenKeys.lists(tenantId),
    queryFn: () => repo.getApiTokens(),
    enabled: !!auth.user?.access_token && !!tenantId,
  });
}

export function useCreateApiTokenMutation(tenantId: string) {
  const repo = useRepository(tenantId);
  return useToastMutation(
    (payload: CreateApiTokenPayload) => repo.createApiToken(payload),
    'API Token created successfully.',
    [apiTokenKeys.lists(tenantId)],
  );
}

export function useUpdateApiTokenMutation(tenantId: string) {
  const repo = useRepository(tenantId);
  return useToastMutation(
    ({ id, data }: { id: string; data: { name?: string; active?: boolean } }) =>
      repo.updateApiToken(id, data),
    (_result, { data }) => {
      if (data.active !== undefined) return data.active ? 'Token activated.' : 'Token deactivated.';
      if (data.name !== undefined) return 'Token renamed.';
      return '';
    },
    [apiTokenKeys.lists(tenantId)],
  );
}

export function useDeleteApiTokenMutation(tenantId: string) {
  const repo = useRepository(tenantId);
  return useToastMutation(
    (id: string) => repo.deleteApiToken(id),
    'API Token permanently deleted.',
    [apiTokenKeys.lists(tenantId)],
  );
}
