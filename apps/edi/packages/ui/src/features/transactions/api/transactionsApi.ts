import { useQuery } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type {
  TransactionDetailResponse,
  TransactionListResponse,
  TransactionThreadResponse,
} from '../types';

export const transactionsKeys = {
  all: ['transactions'] as const,
  lists: () => [...transactionsKeys.all, 'list'] as const,
  list: (params: Record<string, unknown>) => [...transactionsKeys.lists(), params] as const,
  details: () => [...transactionsKeys.all, 'detail'] as const,
  detail: (id: string) => [...transactionsKeys.details(), id] as const,
  threads: () => [...transactionsKeys.all, 'thread'] as const,
  thread: (key: string, value: string) => [...transactionsKeys.threads(), key, value] as const,
};

export function useTransactions(params: {
  limit?: number;
  offset?: number;
  partner_id?: string;
  transaction_type?: string;
  direction?: string;
}) {
  const api = useEdiNetwork();

  return useQuery({
    queryKey: transactionsKeys.list(params),
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.limit !== undefined) searchParams.set('limit', params.limit.toString());
      if (params.offset !== undefined) searchParams.set('offset', params.offset.toString());
      if (params.partner_id) searchParams.set('partner_id', params.partner_id);
      if (params.transaction_type) searchParams.set('transaction_type', params.transaction_type);
      if (params.direction) searchParams.set('direction', params.direction);

      const response = await api.get<TransactionListResponse>(
        `/transactions?${searchParams.toString()}`,
      );
      return response.data;
    },
    refetchInterval: 10000,
  });
}

export function useTransactionDetail(traceId: string) {
  const api = useEdiNetwork();
  return useQuery({
    queryKey: transactionsKeys.detail(traceId),
    queryFn: async () => {
      const response = await api.get<TransactionDetailResponse>(`/transactions/${traceId}`);
      return response.data;
    },
    enabled: !!traceId,
    refetchInterval: 10000,
  });
}

export function useTransactionThread(key: string, value: string) {
  const api = useEdiNetwork();
  return useQuery({
    queryKey: transactionsKeys.thread(key, value),
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      searchParams.set('key', key);
      searchParams.set('value', value);
      const response = await api.get<TransactionThreadResponse>(
        `/transactions/thread?${searchParams.toString()}`,
      );
      return response.data;
    },
    enabled: !!key && !!value,
  });
}
