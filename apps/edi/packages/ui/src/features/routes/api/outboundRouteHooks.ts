import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import type { CreateOutboundRoutePayload, OutboundRouteItem, UpdateRoutePayload } from '../types';

export function useOutboundRoutesQuery() {
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: ['outbound-routes', tenantId],
    queryFn: async (): Promise<OutboundRouteItem[]> => {
      const res = await api.get<OutboundRouteItem[]>('outbound-routes');
      return res.data;
    },
  });
}

export function useCreateOutboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async (payload: CreateOutboundRoutePayload) => {
      await api.post('outbound-routes', payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['outbound-routes', tenantId] });
    },
  });
}

export function useUpdateOutboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async ({ routeId, payload }: { routeId: string; payload: UpdateRoutePayload }) => {
      await api.patch(`outbound-routes/${routeId}`, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['outbound-routes', tenantId] });
    },
  });
}

export function useDeleteOutboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async (routeId: string) => {
      await api.delete(`outbound-routes/${routeId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['outbound-routes', tenantId] });
    },
  });
}
