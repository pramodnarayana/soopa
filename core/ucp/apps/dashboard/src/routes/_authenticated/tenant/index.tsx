import { DashboardProvider, EdiDashboardPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useMemo } from 'react';
import { useAuth } from 'react-oidc-context';
import { HttpDashboardRepository } from '@/lib/HttpDashboardRepository';

export const Route = createFileRoute('/_authenticated/tenant/')({
  component: TenantDashboardWrapper,
});

function TenantDashboardWrapper() {
  const auth = useAuth();
  const tenantId = auth.user?.profile['urn:zitadel:iam:org:id'] as string;

  const dashboardRepository = useMemo(() => {
    if (!tenantId) return null;
    return new HttpDashboardRepository(tenantId);
  }, [tenantId]);

  if (!tenantId || !dashboardRepository) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">Loading tenant information...</p>
      </div>
    );
  }

  return (
    <DashboardProvider repository={dashboardRepository}>
      <EdiDashboardPage />
    </DashboardProvider>
  );
}
