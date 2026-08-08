import { createFileRoute } from '@tanstack/react-router';
import { LayoutDashboard } from 'lucide-react';
import { useTenantContext } from '../../../contexts/TenantContext';
import { useGetTenant } from '../../../domains/tenants/api/queries';

export const Route = createFileRoute('/_authenticated/tenant/')({
  component: TenantDashboard,
});

function TenantDashboard() {
  const { tenantId } = useTenantContext();
  const { data: tenant, isLoading } = useGetTenant(tenantId);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600" />
      </div>
    );
  }

  const activeSubscriptions = tenant?.subscriptions ?? [];

  return (
    <div className="flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
      {/* Page Header */}
      <section className="flex flex-col gap-1 pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
          <LayoutDashboard className="w-8 h-8 text-indigo-600" />
          Dashboard
        </h2>
        <p className="text-slate-500 text-sm">Welcome back, {tenant?.name}.</p>
      </section>

      {/* Active Modules */}
      <section className="flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">
          Active Modules
        </h3>
        {activeSubscriptions.length === 0 ? (
          <p className="text-slate-400 text-sm">
            No active subscriptions. Contact your administrator.
          </p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {activeSubscriptions.map((app) => (
              <span
                key={app}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-50 text-indigo-700 text-sm font-semibold border border-indigo-100"
              >
                {app.toUpperCase()}
              </span>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
