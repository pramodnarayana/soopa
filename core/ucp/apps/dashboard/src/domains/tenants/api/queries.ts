import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: 'active' | 'inactive';
  createdAt: string;
  updatedAt: string;
  zitadelOrgId: string;
  subscriptions: any[];
}

export interface PaginatedTenants {
  items: Tenant[];
  total: number;
  page: number;
  limit: number;
}

export const useGetTenants = () => {
  return useQuery({
    queryKey: ['tenants'],
    queryFn: async () => {
      const response = await apiClient.get<PaginatedTenants>('/tenants');
      return response.items || [];
    },
  });
};

export const useGetTenant = (tenantId?: string) => {
  return useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => apiClient.get<Tenant>(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  });
};
