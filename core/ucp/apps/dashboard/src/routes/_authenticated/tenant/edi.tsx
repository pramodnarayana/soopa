import { EdiUIProvider, SFTPPartnersProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/tenant/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  // Zitadel exposes the Org ID in the profile
  const tenantId = (auth.user?.profile?.['urn:zitadel:iam:org:id'] as string) || 'default';

  const UCP_API_URL =
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000';

  const baseUrl = `${UCP_API_URL}/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider baseUrl={baseUrl} token={token} tenantId={tenantId}>
      <SFTPPartnersProvider>
        <Outlet />
      </SFTPPartnersProvider>
    </EdiUIProvider>
  );
}
