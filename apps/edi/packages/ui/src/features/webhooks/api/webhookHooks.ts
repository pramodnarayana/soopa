import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { UCP_API_URL } from '../../../config/ucp';
import { useTenantId } from '../../../contexts/TenantContext';
import { useToastMutation } from '../../../hooks/use-toast-mutation';
import type { CreateWebhookEndpointPayload } from '../types';
import { createWebhooksRepository } from './webhooksApi';

export const webhooksKeys = {
  all: ['webhooks'] as const,
  tenant: (tenantId: string) => [...webhooksKeys.all, tenantId] as const,
};

function useRepository() {
  const auth = useAuth();
  const tenantId = useTenantId();
  return createWebhooksRepository(auth.user?.access_token ?? '', tenantId, UCP_API_URL);
}

export function useTenantWebhooksQuery() {
  const repo = useRepository();
  const auth = useAuth();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: webhooksKeys.tenant(tenantId),
    queryFn: () => repo.getTenantWebhooks(),
    enabled: !!auth.user?.access_token && !!tenantId,
  });
}

export function useCreateWebhookMutation() {
  const repo = useRepository();
  const tenantId = useTenantId();
  return useToastMutation(
    (payload: CreateWebhookEndpointPayload) => repo.createWebhook(payload),
    'Webhook created successfully.',
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useUpdateWebhookStatusMutation() {
  const repo = useRepository();
  const tenantId = useTenantId();
  return useToastMutation(
    ({ id, active }: { id: string; active: boolean }) => repo.updateWebhookStatus(id, active),
    (_result, { active }) => (active ? 'Webhook activated.' : 'Webhook deactivated.'),
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useUpdateWebhookMutation() {
  const repo = useRepository();
  const tenantId = useTenantId();
  return useToastMutation(
    ({ id, payload }: { id: string; payload: { name?: string; url?: string } }) =>
      repo.updateWebhook(id, payload),
    'Webhook updated.',
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useDeleteWebhookMutation() {
  const repo = useRepository();
  const tenantId = useTenantId();
  return useToastMutation((id: string) => repo.deleteWebhook(id), 'Webhook deleted.', [
    webhooksKeys.tenant(tenantId),
  ]);
}
