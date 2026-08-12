import { WebhooksPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useTenantContext } from '../../../../contexts/TenantContext';
import { getUcpApiUrl } from '../../../../lib/auth';

export const Route = createFileRoute('/_authenticated/tenant_/settings/developer/webhooks')({
  component: WebhooksRoute,
});

function WebhooksRoute() {
  const { tenantId, token } = useTenantContext();

  return <WebhooksPage baseUrl={getUcpApiUrl()} tenantId={tenantId} token={token} />;
}
