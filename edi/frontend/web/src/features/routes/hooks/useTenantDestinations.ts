import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createWebhooksRepository } from '@/features/webhooks/api/webhooksApi';
import { createPartnersRepository } from '@/features/partners/api/partnersApi';
import { Direction } from '../types';

export function useTenantDestinations(direction: Direction) {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';

  return useQuery({
    queryKey: ['destinations', direction],
    queryFn: async () => {
      if (direction === Direction.INBOUND) {
        const webhooksRepo = createWebhooksRepository(token);
        const partnersRepo = createPartnersRepository(token);
        const [webhooks, partners] = await Promise.all([
          webhooksRepo.getTenantWebhooks(),
          partnersRepo.getTenantPartners()
        ]);
        return [
          ...webhooks.map(d => ({ id: d.id, name: d.name, type: d.type })),
          ...partners.map(d => ({ id: d.id, name: d.name, type: d.type, is_local: d.type === 'AS2' ? d.is_local : undefined }))
        ];
      } else {
        const repo = createPartnersRepository(token);
        const data = await repo.getTenantPartners();
        return data.map(d => ({ id: d.id, name: d.name, type: d.type, is_local: d.type === 'AS2' ? d.is_local : undefined }));
      }
    },
    enabled: !!token,
  });
}
