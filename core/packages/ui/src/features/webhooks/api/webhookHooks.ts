import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { CreateWebhookPayload, UpdateWebhookPayload } from '../types';
import { HttpWebhookRepository } from './webhookRepository';

export interface WebhookHookConfig {
  baseUrl: string;
  tenantId: string;
  token: string;
}

const webhookKeys = {
  all: (tenantId: string) => ['platform', 'webhooks', tenantId] as const,
};

function useWebhookRepo({ baseUrl, tenantId, token }: WebhookHookConfig) {
  return new HttpWebhookRepository(baseUrl, tenantId, token);
}

export function useWebhooksQuery(config: WebhookHookConfig) {
  const repo = useWebhookRepo(config);
  return useQuery({
    queryKey: webhookKeys.all(config.tenantId),
    queryFn: () => repo.getAll(),
    enabled: !!config.token && !!config.tenantId,
  });
}

export function useCreateWebhookMutation(config: WebhookHookConfig) {
  const repo = useWebhookRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWebhookPayload) => repo.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
    },
  });
}

export function useUpdateWebhookMutation(config: WebhookHookConfig) {
  const repo = useWebhookRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateWebhookPayload }) =>
      repo.update(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
    },
  });
}

export function useDeleteWebhookMutation(config: WebhookHookConfig) {
  const repo = useWebhookRepo(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repo.delete(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
    },
  });
}
