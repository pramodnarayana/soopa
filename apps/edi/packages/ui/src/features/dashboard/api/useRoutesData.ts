import { useQuery } from '@tanstack/react-query';
import type { RouteItem } from '@/features/routes/types';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';

export type { RouteItem };

export function useRoutesData() {
  const api = useEdiNetwork();

  return useQuery({
    queryKey: ['active-routes'],
    queryFn: async (): Promise<RouteItem[]> => {
      const res = await api.get<RouteItem[]>('/routes');
      return res.data;
    },
  });
}
