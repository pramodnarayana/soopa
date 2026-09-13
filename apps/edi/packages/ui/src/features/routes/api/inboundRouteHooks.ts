import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import type { CreateInboundRoutePayload, InboundRouteItem, UpdateRoutePayload } from '../types';

export function useInboundRoutesQuery() {
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: ['inbound-routes', tenantId],
    queryFn: async (): Promise<InboundRouteItem[]> => {
      const res = await api.get<InboundRouteItem[]>('inbound-routes');
      return res.data;
    },
  });
}

export function useCreateInboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async (payload: CreateInboundRoutePayload) => {
      await api.post('inbound-routes', payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['inbound-routes', tenantId] });
    },
  });
}

export function useUpdateInboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async ({ routeId, payload }: { routeId: string; payload: UpdateRoutePayload }) => {
      await api.patch(`inbound-routes/${routeId}`, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['inbound-routes', tenantId] });
    },
  });
}

export function useDeleteInboundRouteMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async (routeId: string) => {
      await api.delete(`inbound-routes/${routeId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['inbound-routes', tenantId] });
    },
  });
}
