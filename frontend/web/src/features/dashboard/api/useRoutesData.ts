import { useQuery } from '@tanstack/react-query'
import { useAuth } from 'react-oidc-context'
import axios from 'axios'
import type { RouteItem } from '@/features/routes/types'

export type { RouteItem }

export function useRoutesData() {
  const auth = useAuth()

  return useQuery({
    queryKey: ['active-routes'],
    queryFn: async (): Promise<RouteItem[]> => {
      const response = await axios.get('/api/v1/routes', {
        headers: {
          Authorization: `Bearer ${auth.user?.access_token}`
        }
      })
      return response.data
    },
    enabled: !!auth.user?.access_token
  })
}
