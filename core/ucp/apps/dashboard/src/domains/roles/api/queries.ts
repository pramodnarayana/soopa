import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface Role {
  key: string;
  displayName: string;
  group: string;
}

export const useGetRoles = () => {
  return useQuery({
    queryKey: ['roles'],
    queryFn: () => apiClient.get<Role[]>('/tenants/roles'),
  });
};
