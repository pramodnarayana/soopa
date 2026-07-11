import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryKey } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createApiTokenRepository } from './apiTokensApi';
import type { CreateApiTokenPayload } from '../types';
import { useToast } from '@/hooks/use-toast';

export const apiTokenKeys = {
  all: ['apiTokens'] as const,
  lists: () => [...apiTokenKeys.all, 'list'] as const,
};

function useRepository() {
  const auth = useAuth();
  return createApiTokenRepository(auth.user?.access_token ?? '');
}

function useToastMutation<TData, TVariables = any>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string | ((data: TData) => string),
  queryKeysToInvalidate: QueryKey[] = []
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: (data) => {
      queryKeysToInvalidate.forEach(key => {
        queryClient.invalidateQueries({ queryKey: key });
      });
      const message = typeof successMessage === 'function' ? successMessage(data) : successMessage;
      if (message) {
        toast({ title: 'Success', description: message });
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    }
  });
}

export function useApiTokensQuery() {
  const repo = useRepository();
  return useQuery({
    queryKey: apiTokenKeys.lists(),
    queryFn: () => repo.getApiTokens(),
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

export function useRevokeApiTokenMutation() {
  const repo = useRepository();
  return useToastMutation(
    (id: string) => repo.revokeApiToken(id),
    'API Token revoked.',
    [apiTokenKeys.lists()]
  );
}

export function useDeleteApiTokenMutation() {
  const repo = useRepository();
  return useToastMutation(
    (id: string) => repo.deleteApiToken(id),
    'API Token deleted.',
    [apiTokenKeys.lists()]
  );
}
