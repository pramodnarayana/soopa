import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef } from 'react';
import {
  FetchHttpClientAdapter,
  type HttpClientPort,
  ok,
  type PlatformResultQueryView,
  projectPlatformResultQuery,
  recordPlatformMutationOutcome,
} from '../../../network';
import { type FrontendLoggerPort, StructuredJsonLoggerAdapter } from '../../../observability';
import {
  HttpNotificationRepository,
  type InAppNotification,
  type NotificationRepositoryPort,
  NotificationSeverity,
  type NotificationSeverityValue,
} from './notificationRepository';

export type { InAppNotification, NotificationRepositoryPort, NotificationSeverityValue };
export { HttpNotificationRepository, NotificationSeverity };

export interface NotificationContext {
  readonly tenantId: string;
  readonly userId: string;
  readonly accessToken: string;
  readonly apiUrl: string;
  readonly httpClient?: HttpClientPort;
  readonly logger?: FrontendLoggerPort;
}

export const notificationKeys = {
  inApp: (tenantId: string, userId: string) => ['notifications', tenantId, userId] as const,
};

function useNotificationWiring({
  tenantId,
  userId,
  accessToken,
  apiUrl,
  httpClient,
  logger,
}: NotificationContext): {
  readonly repo: NotificationRepositoryPort;
  readonly logger: FrontendLoggerPort;
} {
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;

  return useMemo(() => {
    const resolvedLogger = (logger ?? new StructuredJsonLoggerAdapter()).bind({
      feature: 'notifications_inbox',
      tenant_id: tenantId,
      user_id: userId,
    });
    const resolvedClient =
      httpClient ??
      new FetchHttpClientAdapter({
        baseUrl: apiUrl,
        getToken: () => tokenRef.current,
        logger: resolvedLogger,
      });
    return {
      repo: new HttpNotificationRepository(resolvedClient, tenantId, userId),
      logger: resolvedLogger,
    };
  }, [apiUrl, httpClient, logger, tenantId, userId]);
}

export function useNotifications(
  ctx: NotificationContext,
): PlatformResultQueryView<InAppNotification[]> {
  const { repo } = useNotificationWiring(ctx);
  const query = useQuery({
    queryKey: notificationKeys.inApp(ctx.tenantId, ctx.userId),
    queryFn: async ({ signal }) => {
      if (!ctx.userId || !ctx.tenantId) {
        return ok<InAppNotification[]>([]);
      }
      return repo.listInApp(signal);
    },
    enabled: Boolean(ctx.userId && ctx.tenantId && ctx.accessToken),
  });
  return projectPlatformResultQuery(query);
}

export function useMarkNotificationAsRead(ctx: NotificationContext) {
  const { repo, logger } = useNotificationWiring(ctx);
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (notificationId: string) => {
      if (!ctx.userId || !ctx.tenantId) {
        return ok<void>(undefined);
      }
      return repo.markAsRead(notificationId);
    },
    onSuccess: (result, notificationId) => {
      if (
        recordPlatformMutationOutcome(logger, 'notification.mark_read', result, {
          notification_id: notificationId,
        })
      ) {
        void queryClient.invalidateQueries({
          queryKey: notificationKeys.inApp(ctx.tenantId, ctx.userId),
        });
      }
    },
  });
}
