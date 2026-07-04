import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { RoutesProvider, useRoutes } from '@/features/routes/context/RoutesContext'
import { RoutesTable } from '@/features/routes/components/RoutesTable'
import { CreateRouteModal } from '@/features/routes/components/CreateRouteModal'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/routes',
  component: RoutesPageWrapper,
})

function RoutesPageWrapper() {
  return (
    <RoutesProvider>
      <RoutesPage />
    </RoutesProvider>
  )
}

function RoutesPage() {
  const { routes, isLoading } = useRoutes();

  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Header */}
      <section className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-200/60">
        <div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
            Routing
          </h2>
        </div>
        <div className="shrink-0">
          <CreateRouteModal />
        </div>
      </section>

      {/* Main Content */}
      <section>
        <RoutesTable data={routes} isLoading={isLoading} />
      </section>
    </div>
  )
}
