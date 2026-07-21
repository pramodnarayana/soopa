import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface App {
  id: string;
  name: string;
  slug: string;
  description: string;
}

export const useGetApps = () => {
  return useQuery({
    queryKey: ['apps'],
    queryFn: () => apiClient.get<App[]>('/apps'),
  });
};

export interface Subscription {
  id: string;
  appId: string;
  tenantId: string;
}

export const useGetTenantSubscriptions = (tenantId: string) => {
  return useQuery({
    queryKey: ['tenants', tenantId, 'subscriptions'],
    queryFn: () => apiClient.get<Subscription[]>(`/tenants/${tenantId}/subscriptions`),
    enabled: !!tenantId,
  });
};
