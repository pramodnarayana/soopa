import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import { useUcpNetwork } from '../../../contexts/UcpNetworkContext';
import {
  normalizePartnerResponse,
  PartnersArraySchema,
} from '../../../features/partners/api/partnerSchemas';
import { RawWebhooksArrayResponseSchema } from '../../../features/webhooks/api/webhookSchemas';
import { mapRawWebhook } from '../../../features/webhooks/api/webhookHooks';
import { Direction } from '../types';

export function useTenantDestinations(direction: Direction) {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';
  const tenantId = useTenantId();
  const ediApi = useEdiNetwork();
  const ucpApi = useUcpNetwork();

  return useQuery({
    queryKey: ['destinations', direction, tenantId],
    queryFn: async () => {
      if (direction === Direction.INBOUND) {
        const [webhooksRes, partnersRes] = await Promise.all([
          ucpApi.get(`/tenants/${tenantId}/webhooks`),
          ediApi.get('/trading-partners'),
        ]);

        const rawWebhooks = RawWebhooksArrayResponseSchema.parse(webhooksRes.data);
        const webhooks = rawWebhooks.map((w) => mapRawWebhook(w, tenantId));
        const partners = PartnersArraySchema.parse(partnersRes.data.map(normalizePartnerResponse));

        return [
          ...webhooks.map((d) => ({ id: d.id, name: d.name, type: d.type })),
          ...partners.map((d) => ({
            id: d.id,
            name: d.name,
            type: d.type,
            is_local: d.type === 'AS2' ? d.is_local : undefined,
          })),
        ];
      } else {
        const partnersRes = await ediApi.get('/trading-partners');
        const data = PartnersArraySchema.parse(partnersRes.data.map(normalizePartnerResponse));
        return data.map((d) => ({
          id: d.id,
          name: d.name,
          type: d.type,
          is_local: d.type === 'AS2' ? d.is_local : undefined,
        }));
      }
    },
    enabled: !!token && !!tenantId,
  });
}
