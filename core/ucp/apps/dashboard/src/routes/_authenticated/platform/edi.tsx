import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/platform/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const tenantId =
    ((auth.user?.profile?.idpTenantId || auth.user?.profile?.tenant_id) as string) || 'default';

  const UCP_API_URL =
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000';

  // The UI components append /platform/... to the routes, so we just need /api/v1/
  // to ensure it hits the PlatformProxyController in NestJS which proxies /api/v1/platform.
  // IMPORTANT: The trailing slash is required for correct relative path resolution by
  // the UI components and the shared UI package contract.
  const baseUrl = `${UCP_API_URL}/api/v1/`;

  return (
    <EdiUIProvider baseUrl={baseUrl} ucpBaseUrl={UCP_API_URL} token={token} tenantId={tenantId}>
      <Outlet />
    </EdiUIProvider>
  );
}
