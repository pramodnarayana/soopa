import { createRoute } from '@tanstack/react-router';
import { useDashboardData } from '@/features/dashboard/api/useDashboardData';
import { UserManagementTable } from '@/features/users/components/UserManagementTable';
import { Route as platformRoute } from '../platform';

export const Route = createRoute({
  getParentRoute: () => platformRoute,
  path: '/users',
  component: PlatformUsers,
});

// MOCK DATA FOR PLATFORM
const PLATFORM_USERS = [
  { id: '1', name: 'Alice Smith', email: 'alice@soopa.com', role: 'Owner' as const },
  { id: '2', name: 'Bob Jones', email: 'bob@soopa.com', role: 'Admin' as const },
  { id: '3', name: 'Charlie', email: 'charlie@soopa.com', role: 'Standard' as const },
];

export function PlatformUsers() {
  const { data: userProfile } = useDashboardData();

  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out h-[calc(100vh-8rem)]">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Platform Users</h1>
        <p className="text-slate-500 text-lg">
          Manage Soopa internal staff access and permissions.
        </p>
      </div>

      <UserManagementTable
        users={PLATFORM_USERS}
        currentPermissions={userProfile?.permissions || []}
      />
    </div>
  );
}
