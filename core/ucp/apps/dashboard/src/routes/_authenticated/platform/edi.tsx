import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { config } from '../../../lib/config';

export const Route = createFileRoute('/_authenticated/platform/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const tenantId =
    ((auth.user?.profile?.idpTenantId || auth.user?.profile?.tenant_id) as string) || 'default';

  const baseUrl = `${config.ucpApiUrl}/api/v1/`;

  return (
    <EdiUIProvider
      baseUrl={baseUrl}
      ediPlatformBaseUrl={`${config.ucpApiUrl}/api/v1`}
      ucpBaseUrl={`${config.ucpApiUrl}/api/v1`}
      token={token}
      tenantId={tenantId}
    >
      <Outlet />
    </EdiUIProvider>
  );
}
