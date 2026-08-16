import { fetchEventSource } from '@microsoft/fetch-event-source';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

export interface InAppNotification {
  id: string;
  title: string;
  body: string;
  severity: 'info' | 'high' | 'urgent';
  is_read: boolean;
  created_at: string;
}

class FatalAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FatalAuthError';
  }
}

export interface NotificationContext {
  tenantId: string;
  userId: string;
  accessToken: string;
  apiUrl: string;
}

export function useNotifications({ tenantId, userId, accessToken, apiUrl }: NotificationContext) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!userId || !tenantId || !accessToken || !apiUrl) return;

    const abortController = new AbortController();
    let consecutiveErrorCount = 0;
    const MAX_CONSECUTIVE_ERRORS = 5;

    const connectSSE = async () => {
      try {
        await fetchEventSource(
          `${apiUrl}/${tenantId}/users/${userId}/stream?tenant_id=${tenantId}`,
          {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${accessToken}`,
              Accept: 'text/event-stream',
            },
            signal: abortController.signal,
            onopen: async (response) => {
              if (
                response.ok &&
                response.headers.get('content-type')?.includes('text/event-stream')
              ) {
                consecutiveErrorCount = 0;
                return;
              }
              if (response.status === 401 || response.status === 403) {
                throw new FatalAuthError(`Authentication error: ${response.status}`);
              }
              throw new Error(`Unexpected response: ${response.status} ${response.statusText}`);
            },
            onmessage: (event) => {
              consecutiveErrorCount = 0;
              try {
                const newNotification = JSON.parse(event.data);
                queryClient.setQueryData<InAppNotification[]>(
                  ['notifications', tenantId, userId],
                  (old) => {
                    if (!old) return [newNotification];
                    if (old.some((n) => n.id === newNotification.id)) return old;
                    return [newNotification, ...old];
                  },
                );
              } catch (err) {
                console.error('Failed to parse incoming SSE notification', err);
              }
            },
            onerror: (error) => {
              if (error instanceof FatalAuthError) {
                console.error('Fatal authentication error, stopping SSE:', error);
                abortController.abort();
                throw error;
              }

              console.error('SSE stream error:', error);
              consecutiveErrorCount++;

              if (consecutiveErrorCount >= MAX_CONSECUTIVE_ERRORS) {
                console.error(
                  `SSE connection failed ${MAX_CONSECUTIVE_ERRORS} times consecutively. Closing connection to prevent infinite reconnect loop.`,
                );
                abortController.abort();
                throw error;
              }

              void queryClient.invalidateQueries({ queryKey: ['notifications', tenantId, userId] });

              return undefined;
            },
            onclose: () => {
              throw new Error('SSE stream closed normally');
            },
          },
        );
      } catch (err) {
        console.error('SSE connection aborted or failed:', err);
      }
    };

    void connectSSE();

    return () => {
      abortController.abort();
    };
  }, [userId, tenantId, accessToken, queryClient, apiUrl]);

  return useQuery({
    queryKey: ['notifications', tenantId, userId],
    queryFn: async (): Promise<InAppNotification[]> => {
      if (!userId || !tenantId) return [];

      const res = await fetch(`${apiUrl}/${tenantId}/users/${userId}/in-app`, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });

      if (!res.ok) {
        throw new Error('Failed to fetch notifications');
      }
      return res.json();
    },
    enabled: !!userId && !!tenantId && !!accessToken,
  });
}

export function useMarkNotificationAsRead({
  tenantId,
  userId,
  accessToken,
  apiUrl,
}: NotificationContext) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (notificationId: string) => {
      if (!userId || !tenantId) return;

      const res = await fetch(
        `${apiUrl}/${tenantId}/users/${userId}/in-app/${notificationId}/read`,
        {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        },
      );

      if (!res.ok) {
        throw new Error('Failed to mark as read');
      }
    },
    onSuccess: () => {
      // Invalidate and refetch
      void queryClient.invalidateQueries({ queryKey: ['notifications', tenantId, userId] });
    },
  });
}
