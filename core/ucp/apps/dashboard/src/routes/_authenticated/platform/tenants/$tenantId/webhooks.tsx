import { EdiUIProvider, WebhooksPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantId/webhooks')({
  component: TenantWebhooksPage,
});

function TenantWebhooksPage() {
  const { tenantId } = Route.useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const UCP_API_URL =
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000';

  const baseUrl = `${UCP_API_URL}/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider tenantId={tenantId} baseUrl={baseUrl} token={token}>
      <WebhooksPage />
    </EdiUIProvider>
  );
}
