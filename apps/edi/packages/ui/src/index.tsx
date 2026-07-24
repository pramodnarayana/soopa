export { PartnersProvider } from './features/partners/context/PartnersContext';
export { Dashboard as EdiDashboardPage } from './routes/tenant/dashboard';
export { DevelopersPage } from './routes/tenant/developers';
export { EdiHeadersPage } from './routes/tenant/edi_headers';
export { EdiToolPage } from './routes/tenant/edi_tool';
export { PartnersPage } from './routes/tenant/partners';
export { RoutesPage } from './routes/tenant/routes';
export { TenantUsers as UsersPage } from './routes/tenant/users';
export { WebhooksPage } from './routes/tenant/webhooks';

import { PartnersProvider } from './features/partners/context/PartnersContext';

export function EdiUIProvider({ children }: { children: React.ReactNode }) {
  return <PartnersProvider>{children}</PartnersProvider>;
}
