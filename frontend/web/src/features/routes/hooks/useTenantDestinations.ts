import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createWebhooksRepository } from '@/features/webhooks/api/webhooksApi';
import { createPartnersRepository } from '@/features/partners/api/partnersApi';

export function useTenantDestinations(direction: 'INBOUND' | 'OUTBOUND') {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';

  return useQuery({
    queryKey: ['destinations', direction],
    queryFn: async () => {
      if (direction === 'INBOUND') {
        const repo = createWebhooksRepository(token);
        const data = await repo.getTenantWebhooks();
        return data.map(d => ({ id: d.id, name: d.name, type: d.type }));
      } else {
        const repo = createPartnersRepository(token);
        const data = await repo.getTenantPartners();
        return data.map(d => ({ id: d.id, name: d.name, type: d.type, is_local: d.type === 'AS2' ? d.is_local : undefined }));
      }
    },
    enabled: !!token,
  });
}
