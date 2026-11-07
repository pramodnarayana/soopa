import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';
import { type Subscription, tenantSubscriptionsQueryKey } from './queries';

interface SubscriptionMutationContext {
  readonly previousSubscriptions: Subscription[] | undefined;
  readonly queryKey: ReturnType<typeof tenantSubscriptionsQueryKey>;
}

export const useSubscribeTenant = () => {
  const queryClient = useQueryClient();
  const apiClient = useUcpApiClient();

  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) =>
      apiClient.post(`/tenants/${tenantId}/subscriptions`, { appId }),
    onMutate: async (variables): Promise<SubscriptionMutationContext> => {
      const queryKey = tenantSubscriptionsQueryKey(variables.tenantId);
      await queryClient.cancelQueries({ queryKey });

      const previousSubscriptions = queryClient.getQueryData<Subscription[]>(queryKey);

      queryClient.setQueryData<Subscription[]>(queryKey, (old) => [
        ...(old ?? []),
        {
          id: `${variables.tenantId}_${variables.appId}`,
          appId: variables.appId,
          tenantId: variables.tenantId,
          status: 'active',
        },
      ]);

      return { previousSubscriptions, queryKey };
    },
    onError: (_err, _variables, context) => {
      if (context?.previousSubscriptions) {
        queryClient.setQueryData(context.queryKey, context.previousSubscriptions);
      }
    },
  });
};

export const useUnsubscribeTenant = () => {
  const queryClient = useQueryClient();
  const apiClient = useUcpApiClient();

  return useMutation({
    mutationFn: ({ tenantId, appId }: { tenantId: string; appId: string }) =>
      apiClient.delete(`/tenants/${tenantId}/subscriptions/${appId}`),
    onMutate: async (variables): Promise<SubscriptionMutationContext> => {
      const queryKey = tenantSubscriptionsQueryKey(variables.tenantId);
      await queryClient.cancelQueries({ queryKey });

      const previousSubscriptions = queryClient.getQueryData<Subscription[]>(queryKey);

      queryClient.setQueryData<Subscription[]>(queryKey, (old) =>
        (old ?? []).filter((sub) => sub.appId !== variables.appId),
      );

      return { previousSubscriptions, queryKey };
    },
    onError: (_err, _variables, context) => {
      if (context?.previousSubscriptions) {
        queryClient.setQueryData(context.queryKey, context.previousSubscriptions);
      }
    },
  });
};
