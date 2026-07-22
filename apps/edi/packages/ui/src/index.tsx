export { PartnersProvider } from './features/partners/context/PartnersContext';

export { PartnersPage } from './routes/tenant/partners';
export { EdiHeadersPage } from './routes/tenant/edi_headers';
export { RoutesPage } from './routes/tenant/routes';
export { EdiToolPage } from './routes/tenant/edi_tool';
export { WebhooksPage } from './routes/tenant/webhooks';
export { DevelopersPage } from './routes/tenant/developers';
export { Dashboard as EdiDashboardPage } from './routes/tenant/dashboard';
export { TenantUsers as UsersPage } from './routes/tenant/users';

import { PartnersProvider } from './features/partners/context/PartnersContext';

export function EdiUIProvider({ children }: { children: React.ReactNode }) {
  return (
    <PartnersProvider>
      {children}
    </PartnersProvider>
  );
}
