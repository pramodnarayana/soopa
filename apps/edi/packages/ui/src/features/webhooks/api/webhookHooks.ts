import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { useToastMutation } from '@/hooks/use-toast-mutation';
import type { CreateWebhookEndpointPayload } from '../types';
import { createWebhooksRepository } from './webhooksApi';

export const webhooksKeys = {
  all: ['webhooks'] as const,
  tenant: () => [...webhooksKeys.all, 'tenant'] as const,
};

function useRepository() {
  const auth = useAuth();
  return createWebhooksRepository(auth.user?.access_token ?? '');
}

export function useTenantWebhooksQuery() {
  const repo = useRepository();
  const auth = useAuth();
  return useQuery({
    queryKey: webhooksKeys.tenant(),
    queryFn: () => repo.getTenantWebhooks(),
    enabled: !!auth.user?.access_token,
  });
}

export function useCreateWebhookMutation() {
  const repo = useRepository();
  return useToastMutation(
    (payload: CreateWebhookEndpointPayload) => repo.createWebhook(payload),
    'Webhook created successfully.',
    [webhooksKeys.tenant()],
  );
}

export function useUpdateWebhookStatusMutation() {
  const repo = useRepository();
  return useToastMutation(
    ({ id, active }: { id: string; active: boolean }) => repo.updateWebhookStatus(id, active),
    (_result, { active }) => (active ? 'Webhook activated.' : 'Webhook deactivated.'),
    [webhooksKeys.tenant()],
  );
}

export function useUpdateWebhookMutation() {
  const repo = useRepository();
  return useToastMutation(
    ({ id, payload }: { id: string; payload: { name?: string; url?: string } }) =>
      repo.updateWebhook(id, payload),
    'Webhook updated.',
    [webhooksKeys.tenant()],
  );
}

export function useDeleteWebhookMutation() {
  const repo = useRepository();
  return useToastMutation((id: string) => repo.deleteWebhook(id), 'Webhook deleted.', [
    webhooksKeys.tenant(),
  ]);
}
