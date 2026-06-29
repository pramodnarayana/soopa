import { useQuery } from '@tanstack/react-query'
import { useAuth } from 'react-oidc-context'
import axios from 'axios'

export interface RouteItem {
  route_id: string
  direction: 'INBOUND' | 'OUTBOUND'
  isa_sender_id: string
  isa_receiver_id: string
  destination_type: 'AS2' | 'SFTP' | 'WEBHOOK' | 'UNKNOWN'
  destination_name: string
  status: string
}

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
