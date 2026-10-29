import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { z } from 'zod';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import { useUcpNetwork } from '../../../contexts/UcpNetworkContext';
import {
  normalizePartnerResponse,
  PartnersArraySchema,
} from '../../../features/partners/api/partnerSchemas';
import { Direction } from '../types';

const InboundWebhookSummaryArraySchema = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
  }),
);

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

        const webhooks = InboundWebhookSummaryArraySchema.parse(webhooksRes.data);
        const partnersData = Array.isArray(partnersRes.data) ? partnersRes.data : [];
        const partners = PartnersArraySchema.parse(partnersData.map(normalizePartnerResponse));

        return [
          ...webhooks.map((d) => ({ id: d.id, name: d.name, type: 'WEBHOOK' as const })),
          ...partners.map((d) => ({
            id: d.id,
            name: d.name,
            type: d.type,
            is_local: d.type === 'AS2' ? d.is_local : undefined,
          })),
        ];
      }

      const partnersRes = await ediApi.get('/trading-partners');
      const partnersData = Array.isArray(partnersRes.data) ? partnersRes.data : [];
      const data = PartnersArraySchema.parse(partnersData.map(normalizePartnerResponse));
      return data.map((d) => ({
        id: d.id,
        name: d.name,
        type: d.type,
        is_local: d.type === 'AS2' ? d.is_local : undefined,
      }));
    },
    enabled: !!token && !!tenantId,
  });
}
