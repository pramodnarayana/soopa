import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../_app'
import { useDashboardData } from '@/features/dashboard/api/useDashboardData'
import { IdentityDetailsCard } from '@/features/dashboard/components/IdentityDetailsCard'
import { TenantProvisioningCard } from '@/features/dashboard/components/TenantProvisioningCard'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/dashboard',
  component: Dashboard,
})

function Dashboard() {
  const { data: userProfile, isLoading, error } = useDashboardData()

  return (
    <div className="grid gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-slate-500">Welcome to your enterprise EDI platform.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
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
