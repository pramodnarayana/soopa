import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface TenantUser {
  id: string;
  firstName?: string;
  lastName?: string;
  email: string;
  role: string;
  createdAt?: string;
  state: string;
}

export const useGetTenantUsers = (tenantId: string) => {
  return useQuery({
    queryKey: ['tenants', tenantId, 'users'],
    queryFn: async () => {
      const res = await apiClient.get<{ result: TenantUser[] }>(`/tenants/${tenantId}/users`);
      return res.result || [];
    },
    enabled: !!tenantId,
  });
};
