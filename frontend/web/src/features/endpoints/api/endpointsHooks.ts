import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createEndpointsRepository } from './endpointsApi';

import type { CreateWebhookEndpointPayload } from '../types';

export const endpointsKeys = {
  all: ['endpoints'] as const,
  tenant: () => [...endpointsKeys.all, 'tenant'] as const,
};

function useRepository() {
  const auth = useAuth();
  return createEndpointsRepository(auth.user?.access_token ?? '');
}

import { useToastMutation } from '@/hooks/use-toast-mutation';

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
