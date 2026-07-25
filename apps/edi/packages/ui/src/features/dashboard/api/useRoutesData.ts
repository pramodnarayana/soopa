import { useQuery } from '@tanstack/react-query';
import type { RouteItem } from '@/features/routes/types';
import { useTenantId } from '@/contexts/TenantContext';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';

export type { RouteItem };

export function useRoutesData() {
  const api = useEdiNetwork();
  const tenantId = useTenantId();

  return useQuery({
    queryKey: ['active-routes', tenantId],
    queryFn: async (): Promise<RouteItem[]> => {
      const res = await api.get<RouteItem[]>('/routes');
      return res.data;
    },
  });
}
