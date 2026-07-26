import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  // Zitadel exposes the Org ID in the profile
  const tenantId = (auth.user?.profile?.['urn:zitadel:iam:org:id'] as string) || 'default';

  const baseUrl = `/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider baseUrl={baseUrl} token={token} tenantId={tenantId}>
      <Outlet />
    </EdiUIProvider>
  );
}
