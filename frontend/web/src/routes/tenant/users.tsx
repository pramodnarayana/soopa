import { createRoute } from '@tanstack/react-router'
import { Route as tenantRoute } from '../tenant'
import { UserManagementTable } from '@/features/users/components/UserManagementTable'
import { useDashboardData } from '@/features/dashboard/api/useDashboardData'

export const Route = createRoute({
  getParentRoute: () => tenantRoute,
  path: '/users',
  component: TenantUsers,
})

// MOCK DATA FOR TENANT
const TENANT_USERS = [
  { id: '101', name: 'Dan Customer', email: 'dan@customer.com', role: 'Owner' as const },
  { id: '102', name: 'Eve Customer', email: 'eve@customer.com', role: 'Admin' as const },
  { id: '103', name: 'Frank Customer', email: 'frank@customer.com', role: 'Standard' as const },
]

function TenantUsers() {
  const { data: userProfile } = useDashboardData()

  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out h-[calc(100vh-8rem)]">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">User Management</h1>
        <p className="text-slate-500 text-lg">Manage your team's access and roles.</p>
      </div>

      <UserManagementTable
        users={TENANT_USERS}
        currentPermissions={userProfile?.permissions || []}
      />
    </div>
  )
}
