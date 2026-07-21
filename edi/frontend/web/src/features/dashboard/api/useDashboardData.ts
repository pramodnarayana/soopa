import { useQuery } from '@tanstack/react-query'
import { useAuth } from 'react-oidc-context'
import axios from 'axios'

export function useDashboardData() {
  const auth = useAuth()

  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const response = await axios.get('/api/me', {
        headers: {
          Authorization: `Bearer ${auth.user?.access_token}`
        }
      })
      return response.data
    },
    enabled: !!auth.user?.access_token
  })
}
