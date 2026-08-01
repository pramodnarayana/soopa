import { WebhooksPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/developer/webhooks')({
  component: WebhooksRoute,
});

function WebhooksRoute() {
  const { tenantId, token } = useTenantContext();

  const UCP_API_URL =
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000';

  return <WebhooksPage baseUrl={UCP_API_URL} tenantId={tenantId} token={token} />;
}
