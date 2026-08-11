import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

export interface InAppNotification {
  id: string;
  title: string;
  body: string;
  is_read: boolean;
  created_at: string;
}

const getBaseUrl = () => {
  // Use the unified API via the standard VITE_UCP_API_URL or fallback
  const url = (import.meta as any).env?.VITE_UCP_API_URL;
  if (!url) return 'http://localhost:3000/api/v1/notifications';

  const base = url.replace(/\/+$/, '');
  return `${base}/api/v1/notifications`;
};

export interface NotificationContext {
  tenantId: string;
  userId: string;
  accessToken: string;
}

export function useNotifications({ tenantId, userId, accessToken }: NotificationContext) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!userId || !tenantId || !accessToken) return;

    const eventSource = new EventSource(
      `${getBaseUrl()}/${tenantId}/users/${userId}/stream?token=${accessToken}&tenant_id=${tenantId}`,
    );

    eventSource.onmessage = (event) => {
      try {
        const newNotification = JSON.parse(event.data);
        // Inject directly into React Query cache instantly
        queryClient.setQueryData<InAppNotification[]>(
          ['notifications', tenantId, userId],
          (old) => {
            if (!old) return [newNotification];
            // Prevent duplicates if already fetched
            if (old.some((n) => n.id === newNotification.id)) return old;
            return [newNotification, ...old];
          },
        );
      } catch (err) {
        console.error('Failed to parse incoming SSE notification', err);
      }
    };

    return () => {
      eventSource.close();
    };
  }, [userId, tenantId, queryClient]);

  return useQuery({
    queryKey: ['notifications', tenantId, userId],
    queryFn: async (): Promise<InAppNotification[]> => {
      if (!userId || !tenantId) return [];

      const res = await fetch(`${getBaseUrl()}/${tenantId}/users/${userId}/in-app`, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });

      if (!res.ok) {
        throw new Error('Failed to fetch notifications');
      }
      return res.json();
    },
    enabled: !!userId && !!tenantId,
  });
}

export function useMarkNotificationAsRead({ tenantId, userId, accessToken }: NotificationContext) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (notificationId: string) => {
      if (!userId || !tenantId) return;

      const res = await fetch(
        `${getBaseUrl()}/${tenantId}/users/${userId}/in-app/${notificationId}/read`,
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
