import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryKey } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createEndpointsRepository } from './endpointsApi';
import { useToast } from '@/hooks/use-toast';
import type { CreateWebhookEndpointPayload } from '../types';

export const endpointsKeys = {
  all: ['endpoints'] as const,
  tenant: () => [...endpointsKeys.all, 'tenant'] as const,
};

function useRepository() {
  const auth = useAuth();
  return createEndpointsRepository(auth.user?.access_token ?? '');
}

function useToastMutation<TData, TVariables = any>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string,
  queryKeysToInvalidate: QueryKey[] = []
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryKeysToInvalidate.forEach(key => {
        queryClient.invalidateQueries({ queryKey: key });
      });
      toast({ title: 'Success', description: successMessage });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    }
  });
}

export function useTenantEndpointsQuery() {
  const auth = useAuth();
  const repo = useRepository();
  return useQuery({
    queryKey: endpointsKeys.tenant(),
    queryFn: () => repo.getTenantEndpoints(),
    enabled: !!auth.user?.access_token,
  });
}

export function useCreateWebhookEndpointMutation() {
  const repo = useRepository();

  return useToastMutation(
    (payload: CreateWebhookEndpointPayload) => repo.createWebhookEndpoint(payload),
    'Webhook Endpoint created successfully.',
    [endpointsKeys.tenant()]
  );
}
