import { EdiUIProvider, WebhooksPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/tenants/$tenantId/webhooks')({
  component: TenantWebhooksPage,
});

function TenantWebhooksPage() {
  const { tenantId } = Route.useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const baseUrl = `/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider tenantId={tenantId} baseUrl={baseUrl} token={token}>
      <WebhooksPage />
    </EdiUIProvider>
  );
}
