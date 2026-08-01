import { DashboardProvider, EdiDashboardPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useMemo } from 'react';
import { HttpDashboardRepository } from '@/lib/HttpDashboardRepository';
import { useTenantContext } from '../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/')({
  component: TenantDashboard,
});

function TenantDashboard() {
  const { tenantId } = useTenantContext();

  const dashboardRepository = useMemo(
    () => new HttpDashboardRepository(tenantId),
    [tenantId],
  );

  return (
    <DashboardProvider repository={dashboardRepository}>
      <EdiDashboardPage />
    </DashboardProvider>
  );
}
