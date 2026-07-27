import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated/platform/edi')({
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

  // The UI components append /platform/... to the routes, so we just need /api/v1
  // to ensure it hits the PlatformProxyController in NestJS which proxies /api/v1/platform
  const baseUrl = `${UCP_API_URL}/api/v1`;

  return (
    <EdiUIProvider baseUrl={baseUrl} token={token} tenantId={tenantId}>
      <Outlet />
    </EdiUIProvider>
  );
}
