import { DashboardProvider, EdiDashboardPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useMemo } from 'react';
import { useUcpApiClient } from '@/contexts/UcpApiClientContext';
import { HttpDashboardRepository } from '@/lib/HttpDashboardRepository';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/edi/')({
  component: EdiDashboard,
});

/**
 * EDI Dashboard route.
 *
 * The subscription guard lives in the parent layout (edi.tsx).
 * This component is only rendered if the tenant is subscribed to EDI.
 */
function EdiDashboard() {
  const { tenantId } = useTenantContext();
  const apiClient = useUcpApiClient();
  const dashboardRepository = useMemo(
    () => new HttpDashboardRepository(apiClient, tenantId),
    [apiClient, tenantId],
  );

  return (
    <DashboardProvider repository={dashboardRepository}>
      <EdiDashboardPage />
    </DashboardProvider>
  );
}
