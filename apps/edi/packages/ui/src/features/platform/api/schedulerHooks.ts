import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type { ConfigResponse, JobResponse } from './schedulerApi';


export function useJobsQuery() {
  const api = useEdiNetwork();
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
  const api = useEdiNetwork();
  return useQuery({
    queryKey: ['scheduler', 'config'],
    queryFn: async (): Promise<ConfigResponse[]> => {
      const res = await api.get<ConfigResponse[]>('/platform/scheduler/config');
      return res.data;
    },
  });
}

export function useUpdateConfigMutation() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const res = await api.put<ConfigResponse>(`/platform/scheduler/config/${encodeURIComponent(key)}`, { value });
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['scheduler', 'config'] });
    },
  });
}

export function useUpdateJobMutation() {
  const api = useEdiNetwork();
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
      const res = await api.put<JobResponse>(`/platform/scheduler/jobs/${encodeURIComponent(name)}`, data);
      return res.data;
    },

    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['scheduler', 'jobs'] });
    },
  });
}
