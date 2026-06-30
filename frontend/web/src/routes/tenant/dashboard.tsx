import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { useDashboardData } from '@/features/dashboard/api/useDashboardData'
import { IdentityDetailsCard } from '@/features/dashboard/components/IdentityDetailsCard'
import { TenantProvisioningCard } from '@/features/dashboard/components/TenantProvisioningCard'
import { Activity } from 'lucide-react'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/dashboard',
  component: Dashboard,
})

function Dashboard() {
  const { data: userProfile, isLoading, error } = useDashboardData()

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">

      {/* Hero / Overview Section */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-6 border-b border-slate-200/60">
        <div className="space-y-2">
          {isLoading ? (
            <div className="h-6 w-32 bg-slate-100 rounded animate-pulse mb-2"></div>
          ) : (
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-slate-600 text-xs font-semibold tracking-wide uppercase mb-2">
              <span className="relative inline-flex rounded-full h-2 w-2 bg-slate-400"></span>
              Status Unknown
            </div>
          )}
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
            Platform Overview
          </h2>
          <p className="text-slate-500 text-lg max-w-2xl">
            Monitor active trading partners, transaction flow, and integration health.
          </p>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex flex-col items-end">
            {isLoading ? (
              <div className="h-9 w-20 bg-slate-100 rounded animate-pulse"></div>
            ) : (
              <span className="text-3xl font-black tracking-tighter text-slate-300">--</span>
            )}
            <span className="text-sm font-medium text-slate-500 flex items-center gap-1 mt-1">
              <Activity className="w-4 h-4 text-slate-400" /> Transactions today
            </span>
          </div>
        </div>
      </section>

      {/* Main Grid */}
      <div className="grid gap-8 grid-cols-1 md:grid-cols-2">
        <IdentityDetailsCard />
        <TenantProvisioningCard
          isLoading={isLoading}
          error={error as Error | null}
          userProfile={userProfile}
        />
      </div>
    </div>
  )
}
