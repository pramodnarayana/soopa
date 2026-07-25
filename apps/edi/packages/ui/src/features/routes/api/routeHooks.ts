import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type {
  CreateInboundRoutePayload,
  CreateOutboundRoutePayload,
  RouteItem,
  UpdateRoutePayload,
} from '../types';

function useApi() {
  const api = useEdiNetwork();
  return api;
}

export function useRoutesQuery() {
  const api = useApi();
  return useQuery({
    queryKey: ['routes'],
    queryFn: async (): Promise<RouteItem[]> => {
      const res = await api.get<RouteItem[]>('/routes');
      return res.data;
    },
  });
}

export function useCreateInboundRouteMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateInboundRoutePayload) => {
      await api.post('/routes/inbound', payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useCreateOutboundRouteMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateOutboundRoutePayload) => {
      await api.post('/routes/outbound', payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useUpdateRouteMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      routeId,
      direction,
      payload,
    }: {
      routeId: string;
      direction: 'INBOUND' | 'OUTBOUND';
      payload: UpdateRoutePayload;
    }) => {
      const endpoint =
        direction === 'INBOUND' ? `/routes/inbound/${routeId}` : `/routes/outbound/${routeId}`;
      await api.patch(endpoint, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useDeleteRouteMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      routeId,
      direction,
    }: {
      routeId: string;
      direction: 'INBOUND' | 'OUTBOUND';
    }) => {
      const ep = direction === 'INBOUND' ? 'inbound' : 'outbound';
      await api.delete(`/routes/${ep}/${routeId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}
