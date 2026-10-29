import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef } from 'react';
import {
  FetchHttpClientAdapter,
  type HttpClientPort,
  type PlatformResultQueryView,
  projectPlatformResultQuery,
  recordPlatformMutationOutcome,
} from '../../../network';
import { type FrontendLoggerPort, StructuredJsonLoggerAdapter } from '../../../observability';
import type { CreateWebhookPayload, UpdateWebhookPayload, Webhook } from '../types';
import { HttpWebhookRepository, type WebhookRepositoryPort } from './webhookRepository';

export type { WebhookRepositoryPort };
export { HttpWebhookRepository };

export interface WebhookHookConfig {
  readonly baseUrl: string;
  readonly tenantId: string;
  readonly token: string;
  readonly httpClient?: HttpClientPort;
  readonly logger?: FrontendLoggerPort;
}

export const webhookKeys = {
  all: (tenantId: string) => ['platform', 'webhooks', tenantId] as const,
};

function useWebhookWiring({ baseUrl, tenantId, token, httpClient, logger }: WebhookHookConfig): {
  readonly repo: WebhookRepositoryPort;
  readonly logger: FrontendLoggerPort;
} {
  const tokenRef = useRef(token);
  tokenRef.current = token;

  return useMemo(() => {
    const resolvedLogger = (logger ?? new StructuredJsonLoggerAdapter()).bind({
      feature: 'webhooks',
      tenant_id: tenantId,
    });
    const resolvedClient =
      httpClient ??
      new FetchHttpClientAdapter({
        baseUrl,
        getToken: () => tokenRef.current,
        logger: resolvedLogger,
      });
    return {
      repo: new HttpWebhookRepository(resolvedClient, tenantId),
      logger: resolvedLogger,
    };
  }, [baseUrl, httpClient, logger, tenantId]);
}

export function useWebhooksQuery(config: WebhookHookConfig): PlatformResultQueryView<Webhook[]> {
  const { repo } = useWebhookWiring(config);
  const query = useQuery({
    queryKey: webhookKeys.all(config.tenantId),
    queryFn: ({ signal }) => repo.getAll(signal),
    enabled: Boolean(config.token && config.tenantId),
  });
  return projectPlatformResultQuery(query);
}

export function useCreateWebhookMutation(config: WebhookHookConfig) {
  const { repo, logger } = useWebhookWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWebhookPayload) => repo.create(payload),
    onSuccess: (result) => {
      if (recordPlatformMutationOutcome(logger, 'webhook.create', result)) {
        void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
      }
    },
  });
}

export function useUpdateWebhookMutation(config: WebhookHookConfig) {
  const { repo, logger } = useWebhookWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      readonly id: string;
      readonly payload: UpdateWebhookPayload;
    }) => repo.update(id, payload),
    onSuccess: (result, variables) => {
      if (
        recordPlatformMutationOutcome(logger, 'webhook.update', result, {
          webhook_id: variables.id,
        })
      ) {
        void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
      }
    },
  });
}

export function useDeleteWebhookMutation(config: WebhookHookConfig) {
  const { repo, logger } = useWebhookWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repo.delete(id),
    onSuccess: (result, id) => {
      if (recordPlatformMutationOutcome(logger, 'webhook.delete', result, { webhook_id: id })) {
        void queryClient.invalidateQueries({ queryKey: webhookKeys.all(config.tenantId) });
      }
    },
  });
}
