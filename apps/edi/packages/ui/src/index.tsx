export { TenantProvider, useTenantId } from './contexts/TenantContext';
export { PartnersProvider } from './features/partners/context/PartnersContext';
export { TradingPartnersPage } from './routes/platform/partners';
export { Dashboard as EdiDashboardPage } from './routes/tenant/dashboard';
export { DevelopersPage } from './routes/tenant/developers';
export { EdiHeadersPage } from './routes/tenant/edi_headers';
export { EdiToolPage } from './routes/tenant/edi_tool';
export { TransactionDetailPage } from './routes/tenant/explorer/$traceId';
export { ExplorerPage } from './routes/tenant/explorer/index';
export { TenantIndexPage } from './routes/tenant/index';
export { PartnersPage } from './routes/tenant/partners';
export { RoutesPage } from './routes/tenant/routes';
export { TenantUsers as UsersPage } from './routes/tenant/users';
export { WebhooksPage } from './routes/tenant/webhooks';

import { EdiNetworkProvider } from './contexts/EdiNetworkContext';
import { TenantProvider } from './contexts/TenantContext';
import { PartnersProvider } from './features/partners/context/PartnersContext';

export function EdiUIProvider({
  children,
  tenantId,
  baseUrl,
  token,
}: {
  children: React.ReactNode;
  tenantId?: string;
  baseUrl: string;
  token?: string;
}) {
  return (
    <TenantProvider tenantId={tenantId}>
      <EdiNetworkProvider baseUrl={baseUrl} token={token}>
        <PartnersProvider>{children}</PartnersProvider>
      </EdiNetworkProvider>
    </TenantProvider>
  );
}

export { useEdiNetwork } from './contexts/EdiNetworkContext';
export { DashboardProvider } from './features/dashboard/api/DashboardContext';
export type { IDashboardRepository } from './features/dashboard/api/IDashboardRepository';
export type { DashboardData } from './features/dashboard/api/useDashboardData';
