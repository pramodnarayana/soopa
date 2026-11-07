import { useQuery } from '@tanstack/react-query';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: 'active' | 'inactive';
  createdAt: string;
  updatedAt: string;
  zitadelOrgId: string;
  subscriptions: string[];
}

export interface PaginatedTenants {
  items: Tenant[];
  total: number;
  page: number;
  limit: number;
}

export const useGetTenants = () => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['tenants'],
    queryFn: async () => {
      const response = await apiClient.get<PaginatedTenants>('/tenants');
      return response.items || [];
    },
  });
};

export const useGetTenant = (tenantId?: string) => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => apiClient.get<Tenant>(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  });
};
