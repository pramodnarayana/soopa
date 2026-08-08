import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export const useSubscribeTenant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) =>
      apiClient.post(`/tenants/${tenantId}/subscriptions`, { appId }),
    onMutate: async (variables) => {
      const queryKey = ['tenants', variables.tenantId, 'subscriptions'];
      await queryClient.cancelQueries({ queryKey });

      const previousSubscriptions = queryClient.getQueryData(queryKey);

      // Optimistically add the subscription
      queryClient.setQueryData(queryKey, (old: any) => [
        ...(old || []),
        {
          id: `${variables.tenantId}_${variables.appId}`,
          appId: variables.appId,
          tenantId: variables.tenantId,
          status: 'active',
        },
      ]);

      return { previousSubscriptions, queryKey };
    },
    onError: (_err, _variables, context: any) => {
      if (context?.previousSubscriptions) {
        queryClient.setQueryData(context.queryKey, context.previousSubscriptions);
      }
    },
  });
};

export const useUnsubscribeTenant = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) =>
      apiClient.delete(`/tenants/${tenantId}/subscriptions/${appId}`),
    onMutate: async (variables) => {
      const queryKey = ['tenants', variables.tenantId, 'subscriptions'];
      await queryClient.cancelQueries({ queryKey });

      const previousSubscriptions = queryClient.getQueryData(queryKey);

      // Optimistically remove the subscription
      queryClient.setQueryData(queryKey, (old: any) =>
        (old || []).filter((sub: any) => sub.appId !== variables.appId),
      );

      return { previousSubscriptions, queryKey };
    },
    onError: (_err, _variables, context: any) => {
      if (context?.previousSubscriptions) {
        queryClient.setQueryData(context.queryKey, context.previousSubscriptions);
      }
    },
  });
};
