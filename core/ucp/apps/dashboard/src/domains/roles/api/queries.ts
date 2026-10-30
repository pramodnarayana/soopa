import { useQuery } from '@tanstack/react-query';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';

export interface Role {
  id: string;
  name: string;
  description: string | null;
  capabilities: string[];
}

export const useGetRoles = () => {
  const apiClient = useUcpApiClient();

  return useQuery({
    queryKey: ['roles'],
    queryFn: () => apiClient.get<Role[]>('/tenants/roles'),
  });
};
