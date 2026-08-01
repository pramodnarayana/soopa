export { TenantProvider, useTenantId } from './contexts/TenantContext';
export { SFTPPartnersProvider } from './features/partners/context/SFTPPartnersContext';
export { AS2PartnershipsPage } from './routes/platform/as2-partnerships';
export { TradingPartnersPage } from './routes/platform/partners';
export { SchedulerPage } from './routes/platform/scheduler';
export { Dashboard as EdiDashboardPage } from './routes/tenant/dashboard';
export { DevelopersPage } from './routes/tenant/developers';
export { EdiHeadersPage } from './routes/tenant/edi_headers';
export { EdiToolPage } from './routes/tenant/edi_tool';
export { TransactionDetailPage } from './routes/tenant/explorer/$traceId';
export { ExplorerPage } from './routes/tenant/explorer/index';
export { TenantIndexPage } from './routes/tenant/index';
export { PartnersPage } from './routes/tenant/partners';
export { RoutesPageWrapper as RoutesPage } from './routes/tenant/routes';
export { TenantUsers as UsersPage } from './routes/tenant/users';
export { WebhooksPage } from './routes/tenant/webhooks';

import { EdiNetworkProvider } from './contexts/EdiNetworkContext';
import { TenantProvider } from './contexts/TenantContext';
import { UcpNetworkProvider } from './contexts/UcpNetworkContext';

export function EdiUIProvider({
  children,
  tenantId,
  baseUrl,
  ucpBaseUrl,
  token,
}: {
  children: React.ReactNode;
  tenantId?: string;
  baseUrl: string;
  ucpBaseUrl: string;
  token?: string;
}) {
  return (
    <TenantProvider tenantId={tenantId}>
      <UcpNetworkProvider baseUrl={ucpBaseUrl} token={token}>
        <EdiNetworkProvider baseUrl={baseUrl} token={token}>
          {children}
        </EdiNetworkProvider>
      </UcpNetworkProvider>
    </TenantProvider>
  );
}

export { useEdiNetwork } from './contexts/EdiNetworkContext';
export { useUcpNetwork } from './contexts/UcpNetworkContext';
export { DashboardProvider } from './features/dashboard/api/DashboardContext';
export type { IDashboardRepository } from './features/dashboard/api/IDashboardRepository';
export type { DashboardData } from './features/dashboard/api/useDashboardData';
