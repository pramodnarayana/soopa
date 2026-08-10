import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import type {
  TransactionDetailResponse,
  TransactionListResponse,
  TransactionThreadResponse,
} from '../types';

export const transactionsKeys = {
  all: (tenantId: string) => ['transactions', tenantId] as const,
  lists: (tenantId: string) => [...transactionsKeys.all(tenantId), 'list'] as const,
  list: (tenantId: string, params: Record<string, unknown>) =>
    [...transactionsKeys.lists(tenantId), params] as const,
  details: (tenantId: string) => [...transactionsKeys.all(tenantId), 'detail'] as const,
  detail: (tenantId: string, id: string) => [...transactionsKeys.details(tenantId), id] as const,
  threads: (tenantId: string) => [...transactionsKeys.all(tenantId), 'thread'] as const,
  thread: (tenantId: string, key: string, value: string) =>
    [...transactionsKeys.threads(tenantId), key, value] as const,
};

export function useTransactions(params: {
  limit?: number;
  offset?: number;
  partner_id?: string;
  transaction_type?: string;
  direction?: string;
}) {
  const api = useEdiNetwork();
  const tenantId = useTenantId();

  return useQuery({
    queryKey: transactionsKeys.list(tenantId, params),
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.limit !== undefined) searchParams.set('limit', params.limit.toString());
      if (params.offset !== undefined) searchParams.set('offset', params.offset.toString());
      if (params.partner_id) searchParams.set('partner_id', params.partner_id);
      if (params.transaction_type) searchParams.set('transaction_type', params.transaction_type);
      if (params.direction) searchParams.set('direction', params.direction);

      const response = await api.get<TransactionListResponse>(
        `transactions?${searchParams.toString()}`,
      );
      return response.data;
    },
    refetchInterval: 10000,
  });
}

export function useTransactionDetail(traceId: string) {
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: transactionsKeys.detail(tenantId, traceId),
    queryFn: async () => {
      const response = await api.get<TransactionDetailResponse>(`transactions/${traceId}`);
      return response.data;
    },
    enabled: !!traceId,
    refetchInterval: 10000,
  });
}

export function useTransactionThread(key: string, value: string) {
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  return useQuery({
    queryKey: transactionsKeys.thread(tenantId, key, value),
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      searchParams.set('key', key);
      searchParams.set('value', value);
      const response = await api.get<TransactionThreadResponse>(
        `transactions/thread?${searchParams.toString()}`,
      );
      return response.data;
    },
    enabled: !!key && !!value,
  });
}

export function useReplayTransaction() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async ({ traceId, tier }: { traceId: string; tier: string }) => {
      const response = await api.post(`transactions/${traceId}/replay`, { tier });
      return response.data;
    },
    onSuccess: (_, { traceId }) => {
      // Invalidate the detail query to show the new state
      queryClient.invalidateQueries({ queryKey: transactionsKeys.detail(tenantId, traceId) });
      queryClient.invalidateQueries({ queryKey: transactionsKeys.lists(tenantId) });
    },
  });
}

export function useBulkReplayTransactions() {
  const api = useEdiNetwork();
  const queryClient = useQueryClient();
  const tenantId = useTenantId();

  return useMutation({
    mutationFn: async ({ traceIds, tier }: { traceIds: string[]; tier: string }) => {
      const response = await api.post(`transactions/bulk-replay`, { trace_ids: traceIds, tier });
      return response.data;
    },
    onSuccess: () => {
      // Invalidate all transaction lists to show the new state
      queryClient.invalidateQueries({ queryKey: transactionsKeys.lists(tenantId) });
    },
  });
}
