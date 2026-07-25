import { DevelopersPage, EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/tenants/$tenantId/api-tokens')({
  component: TenantApiTokensPage,
});

function TenantApiTokensPage() {
  const { tenantId } = Route.useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const baseUrl = `/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider tenantId={tenantId} baseUrl={baseUrl} token={token}>
      <DevelopersPage />
    </EdiUIProvider>
  );
}
