/**
 * Fetches the current user's canonical platform identity from the UCP /auth/me endpoint.
 *
 * This provides the resolved canonical `usr_...` ID and must be used in preference to
 * `auth.user?.profile.sub` (the raw Zitadel IDP numeric ID) for all internal platform
 * operations. This enforces the architectural decision that all internal operations use
 * canonical platform IDs, not external IDP identifiers.
 *
 * Uses the `useUcpNetwork` hook (the EDI app's standard UCP API client) for consistency
 * with all other UCP API calls in this app.
 */
import { useQuery } from '@tanstack/react-query';
import { useUcpNetwork } from '../contexts/UcpNetworkContext';

export interface AuthMe {
  authenticated: boolean;
  subject?: string;
  email?: string;
  name?: string;
  tenantId?: string;
  isPlatformAdmin?: boolean;
  capabilities?: string[];
  authorizedTenants?: string[];
}

export function useAuthMe(): { data: AuthMe | undefined; isLoading: boolean } {
  const api = useUcpNetwork();

  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => api.get<AuthMe>('/api/v1/auth/me').then((res) => res.data),
    staleTime: 5 * 60 * 1000, // 5 minutes — identity doesn't change often
  });
}
