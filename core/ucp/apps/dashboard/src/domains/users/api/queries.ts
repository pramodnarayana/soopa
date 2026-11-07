import { useQuery } from '@tanstack/react-query';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';

export interface TenantUser {
  id: string;
  firstName?: string;
  lastName?: string;
  displayName?: string;
  email: string;
  role: string;
  createdAt?: string;
  state: string;
}

export const useGetTenantUsers = (tenantId: string) => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['tenants', tenantId, 'users'],
    queryFn: async () => {
      const res = await apiClient.get<{ result: TenantUser[] }>(`/tenants/${tenantId}/users`);
      return res.result || [];
    },
    enabled: !!tenantId,
  });
};
