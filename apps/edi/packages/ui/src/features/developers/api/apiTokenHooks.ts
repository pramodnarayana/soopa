import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createApiTokenRepository } from './apiTokensApi';
import type { CreateApiTokenPayload } from '../types';
import { useToastMutation } from '@/hooks/use-toast-mutation';

export const apiTokenKeys = {
  all: ['apiTokens'] as const,
  lists: () => [...apiTokenKeys.all, 'list'] as const,
};

function useRepository() {
  const auth = useAuth();
  return createApiTokenRepository(auth.user?.access_token ?? '');
}

export function useApiTokensQuery() {
  const repo = useRepository();
  const auth = useAuth();
  return useQuery({
    queryKey: apiTokenKeys.lists(),
    queryFn: () => repo.getApiTokens(),
    enabled: !!auth.user?.access_token,
  });
}

export function useCreateApiTokenMutation() {
  const repo = useRepository();
  return useToastMutation(
    (payload: CreateApiTokenPayload) => repo.createApiToken(payload),
    'API Token created successfully.',
    [apiTokenKeys.lists()]
  );
}

export function useUpdateApiTokenMutation() {
  const repo = useRepository();
  return useToastMutation(
    ({ id, data }: { id: string; data: { name?: string; active?: boolean } }) =>
      repo.updateApiToken(id, data),
    (_result, { data }) => {
      if (data.active !== undefined) return data.active ? 'Token activated.' : 'Token deactivated.';
      if (data.name !== undefined) return 'Token renamed.';
      return '';
    },
    [apiTokenKeys.lists()]
  );
}

export function useDeleteApiTokenMutation() {
  const repo = useRepository();
  return useToastMutation(
    (id: string) => repo.deleteApiToken(id),
    'API Token permanently deleted.',
    [apiTokenKeys.lists()]
  );
}
