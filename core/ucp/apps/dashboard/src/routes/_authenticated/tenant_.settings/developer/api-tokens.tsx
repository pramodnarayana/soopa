import { ApiTokensPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useTenantContext } from '../../../../contexts/TenantContext';
import { getUcpApiUrl } from '../../../../lib/auth';

export const Route = createFileRoute('/_authenticated/tenant_/settings/developer/api-tokens')({
  component: ApiTokensRoute,
});

function ApiTokensRoute() {
  const { tenantId, token } = useTenantContext();

  return <ApiTokensPage baseUrl={getUcpApiUrl()} tenantId={tenantId} token={token} />;
}
