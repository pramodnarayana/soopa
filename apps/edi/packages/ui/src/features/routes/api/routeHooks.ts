import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createRoutesRepository } from './routesApi';
import type { CreateInboundRoutePayload, CreateOutboundRoutePayload, UpdateRoutePayload } from '../types';

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
      queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useCreateOutboundRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateOutboundRoutePayload) => repo.createOutboundRoute(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}

export function useUpdateRouteMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ routeId, direction, payload }: { routeId: string; direction: 'INBOUND' | 'OUTBOUND'; payload: UpdateRoutePayload }) =>
      repo.updateRoute(routeId, direction, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routes'] });
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
      queryClient.invalidateQueries({ queryKey: ['routes'] });
    },
  });
}
