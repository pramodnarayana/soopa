import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useTenantId } from '../../../contexts/TenantContext';
import { useUcpNetwork } from '../../../contexts/UcpNetworkContext';
import { PartnersArraySchema } from '../../../features/partners/api/partnerSchemas';
import {
  RawWebhooksArrayResponseSchema,
  WebhookSchema,
} from '../../../features/webhooks/api/webhookSchemas';
import type { Webhook } from '../../../features/webhooks/types';
import { Direction } from '../types';

function mapRawWebhook(raw: any, tenantId: string): Webhook {
  return WebhookSchema.parse({
    id: raw.id,
    name: raw.name,
    url: raw.url,
    type: 'WEBHOOK',
    status: raw.active ? 'ACTIVE' : 'INACTIVE',
    tenant_id: tenantId,
  });
}

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
        const partners = PartnersArraySchema.parse(
          partnersRes.data.map((p: any) => ({ ...p, id: p.partner_id || p.id })),
        );

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
        const data = PartnersArraySchema.parse(
          partnersRes.data.map((p: any) => ({ ...p, id: p.partner_id || p.id })),
        );
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
