import { EdiUIProvider, SFTPPartnersProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useTenantContext } from '../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const { tenantId, token } = useTenantContext();

  const UCP_API_URL =
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000';

  const baseUrl = `${UCP_API_URL}/api/v1/tenants/${tenantId}/edi`;

  return (
    <EdiUIProvider baseUrl={baseUrl} ucpBaseUrl={UCP_API_URL} token={token} tenantId={tenantId}>
      <SFTPPartnersProvider>
        <Outlet />
      </SFTPPartnersProvider>
    </EdiUIProvider>
  );
}
