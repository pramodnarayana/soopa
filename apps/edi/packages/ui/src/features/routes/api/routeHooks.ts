import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import type {
  CreateInboundRoutePayload,
  CreateOutboundRoutePayload,
  UpdateRoutePayload,
} from '../types';
import { createRoutesRepository } from './routesApi';

function useRepo() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  if (!token) throw new Error('No token');
  return createRoutesRepository(token);
}

export function useRoutesQuery() {
  const repo = useRepo();
  return useQuery({
    queryKey: ['routes'],
    queryFn: () => repo.getRoutes(),
  });
}

export function useCreateInboundRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateInboundRoutePayload) => repo.createInboundRoute(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useCreateOutboundRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateOutboundRoutePayload) => repo.createOutboundRoute(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useUpdateRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      routeId,
      direction,
      payload,
    }: {
      routeId: string;
      direction: 'INBOUND' | 'OUTBOUND';
      payload: UpdateRoutePayload;
    }) => repo.updateRoute(routeId, direction, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useDeleteRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ routeId, direction }: { routeId: string; direction: 'INBOUND' | 'OUTBOUND' }) =>
      repo.deleteRoute(routeId, direction),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}
