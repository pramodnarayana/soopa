import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { RouteConfigCard } from '@/features/dashboard/components/RouteConfigCard'
import { ActiveRoutesTable } from '@/features/dashboard/components/ActiveRoutesTable'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/routes',
  component: RoutesPage,
})

export function RoutesPage() {
  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">

      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
          Route Configuration
        </h2>
        <p className="text-slate-500 text-lg max-w-2xl">
          Set up and manage EDI routing logic based on ISA Sender and Receiver IDs.
        </p>
      </section>

      {/* Main Grid */}
      <div className="grid gap-8 grid-cols-1 lg:grid-cols-2">
        <div className="lg:col-span-2 xl:col-span-1">
          <RouteConfigCard />
        </div>
      </div>

      <div className="mt-4">
        <ActiveRoutesTable />
      </div>
    </div>
  )
}
