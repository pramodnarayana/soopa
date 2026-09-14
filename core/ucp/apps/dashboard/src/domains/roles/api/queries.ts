import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface Role {
  id: string;
  name: string;
  description: string | null;
  capabilities: string[];
}

export const useGetRoles = () => {
  return useQuery({
    queryKey: ['roles'],
    queryFn: () => apiClient.get<Role[]>('/tenants/roles'),
  });
};
