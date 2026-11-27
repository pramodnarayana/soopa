import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { useAuthUser } from '../../../hooks/useAuthUser';
import { getApiUrl } from '../../../lib/config';

export const Route = createFileRoute('/_authenticated/platform/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const { data: authUser } = useAuthUser();
  const tenantId = authUser?.tenantId ?? authUser?.authorizedTenants?.[0];

  const baseUrl = getApiUrl('/api/v1/');
  const ucpBaseUrl = getApiUrl('/api/v1');

  return (
    <EdiUIProvider baseUrl={baseUrl} ucpBaseUrl={ucpBaseUrl} token={token} tenantId={tenantId}>
      <Outlet />
    </EdiUIProvider>
  );
}
