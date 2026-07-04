import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryKey } from '@tanstack/react-query';
import { useToast } from '@/hooks/use-toast';

export function useToastMutation<TData, TVariables = any>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string,
  queryKeysToInvalidate: QueryKey[] = []
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryKeysToInvalidate.forEach(key => {
        queryClient.invalidateQueries({ queryKey: key });
      });
      toast({ title: 'Success', description: successMessage });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    }
  });
}
