import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { useAuth } from 'react-oidc-context'
import type { ExplorerResponse, ExplorerEdiMessage, ExplorerEdiJson, FilterRule } from '../types'

export const explorerKeys = {
  all: ['explorer'] as const,
  messages: (filters: FilterRule[]) => [...explorerKeys.all, 'messages', filters] as const,
  json: (filters: FilterRule[]) => [...explorerKeys.all, 'json', filters] as const,
}

export function useExplorerEdiMessages(filters: FilterRule[]) {
  const auth = useAuth()

  return useQuery({
    queryKey: explorerKeys.messages(filters),
    queryFn: async () => {
      const response = await axios.post<ExplorerResponse<ExplorerEdiMessage>>(`/api/v1/explorer/edi-messages`,
        { filters },
        { headers: { Authorization: `Bearer ${auth.user?.access_token}` } }
      )
      return response.data
    },
    enabled: !!auth.user?.access_token,
    refetchInterval: 2000,
  })
}

export function useExplorerEdiJson(filters: FilterRule[]) {
  const auth = useAuth()

  return useQuery({
    queryKey: explorerKeys.json(filters),
    queryFn: async () => {
      const response = await axios.post<ExplorerResponse<ExplorerEdiJson>>(`/api/v1/explorer/edi-json`,
        { filters },
        { headers: { Authorization: `Bearer ${auth.user?.access_token}` } }
      )
      return response.data
    },
    enabled: !!auth.user?.access_token,
    refetchInterval: 2000,
  })
}
