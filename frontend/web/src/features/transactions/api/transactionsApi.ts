import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { useAuth } from 'react-oidc-context'
import type { TransactionListResponse, TransactionDetailResponse, TransactionThreadResponse } from '../types'

export const transactionsKeys = {
  all: ['transactions'] as const,
  lists: () => [...transactionsKeys.all, 'list'] as const,
  list: (params: Record<string, any>) => [...transactionsKeys.lists(), params] as const,
  details: () => [...transactionsKeys.all, 'detail'] as const,
  detail: (id: string) => [...transactionsKeys.details(), id] as const,
  threads: () => [...transactionsKeys.all, 'thread'] as const,
  thread: (key: string, value: string) => [...transactionsKeys.threads(), key, value] as const,
}

export function useTransactions(params: {
  limit?: number
  offset?: number
  partner_id?: string
  transaction_type?: string
  direction?: string
}) {
  const auth = useAuth()

  return useQuery({
    queryKey: transactionsKeys.list(params),
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.limit !== undefined) searchParams.set('limit', params.limit.toString())
      if (params.offset !== undefined) searchParams.set('offset', params.offset.toString())
      if (params.partner_id) searchParams.set('partner_id', params.partner_id)
      if (params.transaction_type) searchParams.set('transaction_type', params.transaction_type)
      if (params.direction) searchParams.set('direction', params.direction)

      const response = await axios.get<TransactionListResponse>(`/api/v1/transactions?${searchParams.toString()}`, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      })
      return response.data
    },
    enabled: !!auth.user?.access_token,
    refetchInterval: 10000,
  })
}

export function useTransactionDetail(traceId: string) {
  const auth = useAuth()
  return useQuery({
    queryKey: transactionsKeys.detail(traceId),
    queryFn: async () => {
      const response = await axios.get<TransactionDetailResponse>(`/api/v1/transactions/${traceId}`, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      })
      return response.data
    },
    enabled: !!traceId && !!auth.user?.access_token,
    refetchInterval: 10000,
  })
}

export function useTransactionThread(key: string, value: string) {
  const auth = useAuth()
  return useQuery({
    queryKey: transactionsKeys.thread(key, value),
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      searchParams.set('key', key)
      searchParams.set('value', value)
      const response = await axios.get<TransactionThreadResponse>(`/api/v1/transactions/thread?${searchParams.toString()}`, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      })
      return response.data
    },
    enabled: !!key && !!value && !!auth.user?.access_token,
  })
}
