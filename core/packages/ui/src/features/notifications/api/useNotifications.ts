import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export interface InAppNotification {
  id: string;
  title: string;
  body: string;
  severity: 'info' | 'high' | 'urgent';
  is_read: boolean;
  created_at: string;
}

export interface NotificationContext {
  tenantId: string;
  userId: string;
  accessToken: string;
  apiUrl: string;
}

export function useNotifications({ tenantId, userId, accessToken, apiUrl }: NotificationContext) {
  const queryClient = useQueryClient();

  // TODO: Implement real-time SSE push for in-app notifications.
  // When ready, restore a useEffect here that connects to:
  //   GET ${apiUrl}/${tenantId}/users/${userId}/stream
  // The backend must implement the corresponding /stream endpoint in the
  // unified-api in_app_notifications_router before re-enabling this.
  // Notifications are currently loaded via REST on page load only.

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
