/**
 * API hooks for Notification Preferences (routing rules) and Templates.
 * Composes HttpNotificationConfigRepository over HttpClientPort + StructuredJsonLoggerAdapter
 * and returns Result<T, ApiProblem> without throwing exceptions.
 */

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
import {
  HttpNotificationConfigRepository,
  type NotificationConfigRepositoryPort,
  type NotificationPreference,
  type NotificationTemplate,
  type PreviewNotificationTemplateInput,
  type PreviewResult,
  type UpsertNotificationTemplateInput,
} from './notificationConfigRepository';

export type {
  NotificationConfigRepositoryPort,
  NotificationPreference,
  NotificationTemplate,
  PreviewNotificationTemplateInput,
  PreviewResult,
  UpsertNotificationTemplateInput,
};
export { HttpNotificationConfigRepository };

export interface NotificationConfigContext {
  readonly tenantId: string;
  readonly accessToken: string;
  readonly apiUrl: string;
  readonly httpClient?: HttpClientPort;
  readonly logger?: FrontendLoggerPort;
}

export const notificationConfigKeys = {
  preferences: (tenantId: string) => ['notification-preferences', tenantId] as const,
  templates: (tenantId: string) => ['notification-templates', tenantId] as const,
};

function useNotificationConfigWiring({
  tenantId,
  accessToken,
  apiUrl,
  httpClient,
  logger,
}: NotificationConfigContext): {
  readonly repo: NotificationConfigRepositoryPort;
  readonly logger: FrontendLoggerPort;
} {
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;

  return useMemo(() => {
    const resolvedLogger = (logger ?? new StructuredJsonLoggerAdapter()).bind({
      feature: 'notification_config',
      tenant_id: tenantId,
    });
    const resolvedClient =
      httpClient ??
      new FetchHttpClientAdapter({
        baseUrl: apiUrl,
        getToken: () => tokenRef.current,
        logger: resolvedLogger,
      });
    return {
      repo: new HttpNotificationConfigRepository(resolvedClient, tenantId),
      logger: resolvedLogger,
    };
  }, [apiUrl, httpClient, logger, tenantId]);
}

export function usePreferences(
  ctx: NotificationConfigContext,
): PlatformResultQueryView<NotificationPreference[]> {
  const { repo } = useNotificationConfigWiring(ctx);
  const query = useQuery({
    queryKey: notificationConfigKeys.preferences(ctx.tenantId),
    queryFn: ({ signal }) => repo.listPreferences(signal),
    enabled: Boolean(ctx.tenantId && ctx.accessToken),
  });
  return projectPlatformResultQuery(query);
}

export function useUpsertPreference(ctx: NotificationConfigContext) {
  const { repo, logger } = useNotificationConfigWiring(ctx);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      event_type,
      channels,
    }: {
      readonly event_type: string;
      readonly channels: readonly string[];
    }) => repo.upsertPreference(event_type, channels),
    onSuccess: (result, variables) => {
      if (
        recordPlatformMutationOutcome(logger, 'notification_preference.upsert', result, {
          event_type: variables.event_type,
        })
      ) {
        void qc.invalidateQueries({
          queryKey: notificationConfigKeys.preferences(ctx.tenantId),
        });
      }
    },
  });
}

export function useDeletePreference(ctx: NotificationConfigContext) {
  const { repo, logger } = useNotificationConfigWiring(ctx);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (event_type: string) => repo.deletePreference(event_type),
    onSuccess: (result, eventType) => {
      if (
        recordPlatformMutationOutcome(logger, 'notification_preference.delete', result, {
          event_type: eventType,
        })
      ) {
        void qc.invalidateQueries({
          queryKey: notificationConfigKeys.preferences(ctx.tenantId),
        });
      }
    },
  });
}

export function useTemplates(
  ctx: NotificationConfigContext,
): PlatformResultQueryView<NotificationTemplate[]> {
  const { repo } = useNotificationConfigWiring(ctx);
  const query = useQuery({
    queryKey: notificationConfigKeys.templates(ctx.tenantId),
    queryFn: ({ signal }) => repo.listTemplates(signal),
    enabled: Boolean(ctx.tenantId && ctx.accessToken),
  });
  return projectPlatformResultQuery(query);
}

export function useUpsertTemplate(ctx: NotificationConfigContext) {
  const { repo, logger } = useNotificationConfigWiring(ctx);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpsertNotificationTemplateInput) => repo.upsertTemplate(payload),
    onSuccess: (result, payload) => {
      if (
        recordPlatformMutationOutcome(logger, 'notification_template.upsert', result, {
          event_type: payload.event_type,
          channel: payload.channel,
        })
      ) {
        void qc.invalidateQueries({
          queryKey: notificationConfigKeys.templates(ctx.tenantId),
        });
      }
    },
  });
}

export function useDeleteTemplate(ctx: NotificationConfigContext) {
  const { repo, logger } = useNotificationConfigWiring(ctx);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) => repo.deleteTemplate(templateId),
    onSuccess: (result, templateId) => {
      if (
        recordPlatformMutationOutcome(logger, 'notification_template.delete', result, {
          template_id: templateId,
        })
      ) {
        void qc.invalidateQueries({
          queryKey: notificationConfigKeys.templates(ctx.tenantId),
        });
      }
    },
  });
}

export function usePreviewTemplate(ctx: NotificationConfigContext) {
  const { repo, logger } = useNotificationConfigWiring(ctx);
  return useMutation({
    mutationFn: (payload: PreviewNotificationTemplateInput) => repo.previewTemplate(payload),
    onSuccess: (result) => {
      recordPlatformMutationOutcome(logger, 'notification_template.preview', result);
    },
  });
}
