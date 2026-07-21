import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export const useSubscribeTenant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) => 
      apiClient.post(`/tenants/${tenantId}/subscriptions`, { appId }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'subscriptions'] });
    },
  });
};

export const useUnsubscribeTenant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) => 
      apiClient.delete(`/tenants/${tenantId}/subscriptions/${appId}`),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'subscriptions'] });
    },
  });
};
