import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type { ConfigResponse, JobResponse } from './schedulerApi';

function useApi() {
  const api = useEdiNetwork();
  return api;
}

export function useJobsQuery() {
  const api = useApi();
  return useQuery({
    queryKey: ['scheduler', 'jobs'],
    queryFn: async (): Promise<JobResponse[]> => {
      const res = await api.get<JobResponse[]>('/platform/scheduler/jobs');
      return res.data;
    },
    refetchInterval: 10000,
  });
}

export function useConfigQuery() {
  const api = useApi();
  return useQuery({
    queryKey: ['scheduler', 'config'],
    queryFn: async (): Promise<ConfigResponse[]> => {
      const res = await api.get<ConfigResponse[]>('/platform/scheduler/config');
      return res.data;
    },
  });
}

export function useUpdateConfigMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const res = await api.put<ConfigResponse>(`/platform/scheduler/config/${key}`, { value });
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['scheduler', 'config'] });
    },
  });
}

export function useUpdateJobMutation() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      name,
      data,
    }: {
      name: string;
      data: {
        interval_seconds?: number | null;
        cron_expression?: string | null;
        timezone?: string | null;
        status?: string;
      };
    }) => {
      const res = await api.put<JobResponse>(`/platform/scheduler/jobs/${name}`, data);
      return res.data;
    },

    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['scheduler', 'jobs'] });
    },
  });
}
