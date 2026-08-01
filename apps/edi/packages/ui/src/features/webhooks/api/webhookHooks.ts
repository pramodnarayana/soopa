import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { useTenantId } from '../../../contexts/TenantContext';
import { useUcpNetwork } from '../../../contexts/UcpNetworkContext';
import { useToastMutation } from '../../../hooks/use-toast-mutation';
import type { CreateWebhookEndpointPayload, Webhook } from '../types';
import {
  RawWebhook,
  RawWebhookResponseSchema,
  RawWebhooksArrayResponseSchema,
  WebhookSchema,
} from './webhookSchemas';

export const webhooksKeys = {
  all: ['webhooks'] as const,
  tenant: (tenantId: string) => [...webhooksKeys.all, tenantId] as const,
};

export function mapRawWebhook(raw: RawWebhook, tenantId: string): Webhook {
  return WebhookSchema.parse({
    id: raw.id,
    name: raw.name,
    url: raw.url,
    type: 'WEBHOOK',
    status: raw.active ? 'ACTIVE' : 'INACTIVE',
    tenant_id: tenantId,
  });
}

export function useTenantWebhooksQuery() {
  const api = useUcpNetwork();
  const auth = useAuth();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: webhooksKeys.tenant(tenantId),
    queryFn: async () => {
      const res = await api.get(`/tenants/${tenantId}/webhooks`);
      const rawWebhooks = RawWebhooksArrayResponseSchema.parse(res.data);
      return rawWebhooks.map((w) => mapRawWebhook(w, tenantId));
    },
    enabled: !!auth.user?.access_token && !!tenantId,
  });
}

export function useCreateWebhookMutation() {
  const api = useUcpNetwork();
  const tenantId = useTenantId();
  return useToastMutation(
    async (payload: CreateWebhookEndpointPayload) => {
      const res = await api.post(`/tenants/${tenantId}/webhooks`, payload);
      const rawWebhook = RawWebhookResponseSchema.parse(res.data);
      return mapRawWebhook(rawWebhook, tenantId);
    },
    'Webhook created successfully.',
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useUpdateWebhookStatusMutation() {
  const api = useUcpNetwork();
  const tenantId = useTenantId();
  return useToastMutation(
    async ({ id, active }: { id: string; active: boolean }) => {
      const res = await api.patch(`/tenants/${tenantId}/webhooks/${id}`, { active });
      const rawWebhook = RawWebhookResponseSchema.parse(res.data);
      return mapRawWebhook(rawWebhook, tenantId);
    },
    (_result, { active }) => (active ? 'Webhook activated.' : 'Webhook deactivated.'),
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useUpdateWebhookMutation() {
  const api = useUcpNetwork();
  const tenantId = useTenantId();
  return useToastMutation(
    async ({ id, payload }: { id: string; payload: { name?: string; url?: string } }) => {
      const res = await api.patch(`/tenants/${tenantId}/webhooks/${id}`, payload);
      const rawWebhook = RawWebhookResponseSchema.parse(res.data);
      return mapRawWebhook(rawWebhook, tenantId);
    },
    'Webhook updated.',
    [webhooksKeys.tenant(tenantId)],
  );
}

export function useDeleteWebhookMutation() {
  const api = useUcpNetwork();
  const tenantId = useTenantId();
  return useToastMutation(
    async (id: string) => {
      await api.delete(`/tenants/${tenantId}/webhooks/${id}`);
    },
    'Webhook deleted.',
    [webhooksKeys.tenant(tenantId)],
  );
}
