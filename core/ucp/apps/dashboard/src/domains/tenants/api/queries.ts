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

export const useGetTenants = () => {
  return useQuery({
    queryKey: ['tenants'],
    queryFn: () => apiClient.get<Tenant[]>('/tenants'),
  });
};

export const useGetTenant = (tenantId?: string) => {
  return useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => apiClient.get<Tenant>(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  });
};
