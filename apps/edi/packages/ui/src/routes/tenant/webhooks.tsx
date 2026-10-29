import { WebhooksPage as SharedWebhooksPage } from '@soopa/ui';
import { createRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { UCP_API_URL } from '../../config/ucp';
import { useTenantId } from '../../contexts/TenantContext';
import { Route as appRoute } from '../tenant';

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/webhooks',
  component: WebhooksPage,
});

export function WebhooksPage() {
  const auth = useAuth();
  const tenantId = useTenantId();
  const token = auth.user?.access_token ?? '';

  return (
    <div className="p-8">
      <SharedWebhooksPage baseUrl={UCP_API_URL} tenantId={tenantId} token={token} />
    </div>
  );
}
