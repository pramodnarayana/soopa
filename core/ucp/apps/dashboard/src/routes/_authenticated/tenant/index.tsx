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
    return new HttpDashboardRepository(tenantId || '');
  }, [tenantId]);

  return (
    <DashboardProvider repository={dashboardRepository}>
      <EdiDashboardPage />
    </DashboardProvider>
  );
}
