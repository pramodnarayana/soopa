import { createRoute } from '@tanstack/react-router';
import { CreateEdiHeaderModal } from '../../features/edi_headers/components/CreateEdiHeaderModal';
import { EdiHeadersTable } from '../../features/edi_headers/components/EdiHeadersTable';
import { CreateInboundRouteModal } from '../../features/routes/components/CreateInboundRouteModal';
import { CreateOutboundRouteModal } from '../../features/routes/components/CreateOutboundRouteModal';
import { RoutesTable } from '../../features/routes/components/RoutesTable';
import { RoutesProvider, useRoutes } from '../../features/routes/context/RoutesContext';
import { Route as appRoute } from '../tenant';

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/edi_setup',
  component: EdiSetupPageWrapper,
});

export function EdiSetupPageWrapper() {
  return (
    <RoutesProvider>
      <EdiSetupPage />
    </RoutesProvider>
  );
}

export function EdiSetupPage() {
  const { routes, isLoading } = useRoutes();

  const inboundRoutes = routes.filter((r) => r.direction === 'INBOUND');
  const outboundRoutes = routes.filter((r) => r.direction === 'OUTBOUND');

  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Page Header */}
      <section className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-border">
        <div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-foreground flex items-center gap-3">
            EDI Setup
          </h2>
          <p className="text-muted-foreground text-sm mt-2">
            Configure inbound and outbound routing and EDI headers.
          </p>
        </div>
      </section>

      <div className="space-y-12">
        {/* Inbound Section */}
        <section className="bg-card text-card-foreground border border-border/60 rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-border/40 bg-muted/20 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-foreground uppercase tracking-wider">
                INBOUND
              </h2>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <CreateInboundRouteModal />
            </div>
          </div>
          <div className="p-6 space-y-4">
            <h3 className="text-sm font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-500"></span>
              Inbound Routes
            </h3>
            <RoutesTable data={inboundRoutes} isLoading={isLoading} />
          </div>
        </section>

        {/* Outbound Section */}
        <section className="bg-card text-card-foreground border border-border/60 rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-border/40 bg-muted/20 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-foreground uppercase tracking-wider">
                OUTBOUND
              </h2>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <CreateEdiHeaderModal />
              <CreateOutboundRouteModal />
            </div>
          </div>

          <div className="p-6 space-y-10">
            <div className="space-y-4">
              <h3 className="text-sm font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
                EDI Headers
              </h3>
              <EdiHeadersTable />
            </div>

            <div className="space-y-4">
              <h3 className="text-sm font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                Outbound Routes
              </h3>
              <RoutesTable data={outboundRoutes} isLoading={isLoading} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
