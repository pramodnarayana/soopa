import { EdiUIProvider, SFTPPartnersProvider } from '@soopa/edi-ui';
import { AppNotSubscribed } from '@soopa/ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { Loader2 } from 'lucide-react';
import { useTenantContext } from '../../../contexts/TenantContext';
import { useGetTenant } from '../../../domains/tenants/api/queries';
import { getApiUrl } from '../../../lib/config';

export const Route = createFileRoute('/_authenticated/tenant/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  const { tenantId, token } = useTenantContext();

  const { data: tenant, isLoading } = useGetTenant(tenantId);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center min-h-full">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  const isEdiSubscribed = !!tenant?.subscriptions?.includes('edi');

  if (!isEdiSubscribed) {
    return <AppNotSubscribed appName="EDI" />;
  }

  const baseUrl = getApiUrl(`/api/v1/tenants/${tenantId}/edi/`);
  const ucpBaseUrl = getApiUrl('/api/v1');

  return (
    <EdiUIProvider baseUrl={baseUrl} ucpBaseUrl={ucpBaseUrl} token={token} tenantId={tenantId}>
      <SFTPPartnersProvider>
        <Outlet />
      </SFTPPartnersProvider>
    </EdiUIProvider>
  );
}
