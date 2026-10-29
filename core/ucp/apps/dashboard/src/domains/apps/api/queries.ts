import { useQuery } from '@tanstack/react-query';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';

export interface App {
  id: string;
  name: string;
  slug: string;
  description: string;
}

export const useGetApps = () => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['apps'],
    queryFn: () => apiClient.get<App[]>('/apps'),
  });
};

export interface Subscription {
  id: string;
  appId: string;
  tenantId: string;
  status: 'active' | 'inactive';
}

export const useGetTenantSubscriptions = (tenantId: string) => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['tenants', tenantId, 'subscriptions'],
    queryFn: () => apiClient.get<Subscription[]>(`/tenants/${tenantId}/subscriptions`),
    enabled: !!tenantId,
  });
};
