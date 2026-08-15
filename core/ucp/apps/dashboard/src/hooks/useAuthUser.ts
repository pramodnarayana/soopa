import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export interface AuthUser {
  authenticated: boolean;
  subject?: string;
  email?: string;
  name?: string;
  tenantId?: string;
  isPlatformAdmin?: boolean;
  capabilities?: string[];
  authorizedTenants?: string[];
}

export const useAuthUser = () => {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => apiClient.get<AuthUser>('/auth/me'),
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false,
  });
};
