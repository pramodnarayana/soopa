import { createRoute } from '@tanstack/react-router';
import { Activity } from 'lucide-react';
import { useDashboardData } from '../../features/dashboard/api/useDashboardData';
import { IdentityDetailsCard } from '../../features/dashboard/components/IdentityDetailsCard';
import { TenantProvisioningCard } from '../../features/dashboard/components/TenantProvisioningCard';
import { Route as appRoute } from '../platform';

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/dashboard',
  component: Dashboard,
});

export function Dashboard() {
  const { data: userProfile, isLoading, error } = useDashboardData();

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Hero / Overview Section */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-6 border-b border-slate-200/60">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-emerald-700 text-xs font-semibold tracking-wide uppercase mb-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            System Operational
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
            Platform Overview
          </h2>
          <p className="text-slate-500 text-lg max-w-2xl">
            Monitor active trading partners, transaction flow, and integration health.
          </p>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex flex-col items-end">
            <span className="text-3xl font-black tracking-tighter text-slate-900">24.8k</span>
            <span className="text-sm font-medium text-slate-500 flex items-center gap-1">
              <Activity className="w-4 h-4 text-emerald-500" /> Transactions today
            </span>
          </div>
        </div>
      </section>

      {/* Main Grid */}
      <div className="grid gap-8 grid-cols-1 md:grid-cols-2">
        <IdentityDetailsCard />
        <TenantProvisioningCard isLoading={isLoading} error={error} userProfile={userProfile} />
      </div>
    </div>
  );
}
