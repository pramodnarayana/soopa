import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTenantContext } from '@/contexts/TenantContext';
import { useAuthUser } from '@/hooks/useAuthUser';
import { apiClient } from '@/lib/api-client';

export interface UserNotificationPreference {
  id: string;
  tenant_id: string;
  user_id: string;
  event_type: string;
  channel: string;
  is_enabled: boolean;
}

export const useUserPreferences = () => {
  const { tenantId } = useTenantContext();
  const { data: user } = useAuthUser();

  return useQuery({
    queryKey: ['user-notification-preferences', tenantId, user?.subject],
    queryFn: async (): Promise<UserNotificationPreference[]> => {
      if (!tenantId || !user?.subject) throw new Error('No tenant or user');
      return apiClient.get(`/users/${tenantId}/${user.subject}/notification-preferences`);
    },
    enabled: !!tenantId && !!user?.subject,
  });
};

export const useUpdateUserPreference = () => {
  const { tenantId } = useTenantContext();
  const { data: user } = useAuthUser();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      eventType,
      channel,
      isEnabled,
    }: {
      eventType: string;
      channel: string;
      isEnabled: boolean;
    }) => {
      if (!tenantId || !user?.subject) throw new Error('No tenant or user');
      return apiClient.patch(
        `/users/${tenantId}/${user.subject}/notification-preferences/${eventType}/${channel}`,
        { is_enabled: isEnabled },
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['user-notification-preferences', tenantId, user?.subject],
      });
    },
  });
};
