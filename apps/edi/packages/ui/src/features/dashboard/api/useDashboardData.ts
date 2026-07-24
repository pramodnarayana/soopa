import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { useAuth } from 'react-oidc-context';

export interface DashboardData {
  id?: string;
  name?: string;
  email?: string;
  permissions?: string[];
  status?: string;
  tenant_id?: number;
  rls_enforced_tenant?: string | null;
  [key: string]: unknown;
}
export function useDashboardData() {
  const auth = useAuth();

  return useQuery({
    queryKey: ['me'],
    queryFn: async (): Promise<DashboardData> => {
      const response = await axios.get<DashboardData>('/api/me', {
        headers: {
          Authorization: `Bearer ${auth.user?.access_token}`,
        },
      });
      return response.data;
    },
    enabled: !!auth.user?.access_token,
  });
}
