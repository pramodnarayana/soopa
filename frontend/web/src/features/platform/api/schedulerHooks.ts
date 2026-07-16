import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createSchedulerRepository } from './schedulerApi';

function useRepo() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  if (!token) throw new Error('No token');
  return createSchedulerRepository(token);
}

export function useJobsQuery() {
  const repo = useRepo();
  return useQuery({
    queryKey: ['scheduler', 'jobs'],
    queryFn: () => repo.getJobs(),
    refetchInterval: 10000,
  });
}

export function useConfigQuery() {
  const repo = useRepo();
  return useQuery({
    queryKey: ['scheduler', 'config'],
    queryFn: () => repo.getConfig(),
  });
}

export function useUpdateConfigMutation() {
  const repo = useRepo();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: any }) => repo.updateConfig(key, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduler', 'config'] });
    },
  });
}
