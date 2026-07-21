import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryKey } from '@tanstack/react-query';
import { useToast } from '@/hooks/use-toast';

/**
 * Shared React Query mutation helper that automatically:
 * - Invalidates supplied query keys on success
 * - Shows a success toast (static string or derived from response data)
 * - Shows an error toast on failure
 */
export function useToastMutation<TData, TVariables = void>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string | ((data: TData, variables: TVariables) => string),
  queryKeysToInvalidate: QueryKey[] = []
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: (data, variables) => {
      queryKeysToInvalidate.forEach((key) => {
        queryClient.invalidateQueries({ queryKey: key });
      });
      const message =
        typeof successMessage === 'function'
          ? successMessage(data, variables)
          : successMessage;
      if (message) {
        toast({ title: 'Success', description: message });
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}
