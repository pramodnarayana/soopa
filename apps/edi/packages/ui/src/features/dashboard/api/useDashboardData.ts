import { useQuery } from '@tanstack/react-query';
import { useDashboardRepository } from './DashboardContext';

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
  const repository = useDashboardRepository();

  return useQuery({
    queryKey: ['dashboard_data'],
    queryFn: () => repository.getDashboardData(),
  });
}
