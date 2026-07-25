import { createFileRoute, Link, Outlet } from '@tanstack/react-router';
import { ArrowLeft, Box, Building2, Code2, Key, Network, Users } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { useGetTenants } from '@/domains/tenants/api/queries';

export const Route = createFileRoute('/_authenticated/tenants/$tenantId')({
  component: TenantLayout,
});

function TenantLayout() {
  const { tenantId } = Route.useParams();

  const { data: tenants = [], isLoading } = useGetTenants();

  const tenant = tenants.find(
    (t: { id: string; name: string; status: string }) => t.id === tenantId,
  );

  if (isLoading) {
    return (
      <div className="p-8 max-w-7xl mx-auto space-y-6">
        <Skeleton className="h-10 w-48 rounded-lg" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (!tenant) {
    return <div className="p-8">Tenant not found</div>;
  }

  return (
    <div className="flex flex-col min-h-full">
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-8 py-6">
          <div className="mb-4">
            <Link
              to="/tenants"
              className="inline-flex items-center text-sm font-medium text-slate-500 hover:text-indigo-600 transition-colors"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back to Tenants
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
              <Building2 className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{tenant.name}</h1>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${tenant.status === 'active' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-700 border-slate-200'}`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${tenant.status === 'active' ? 'bg-emerald-500' : 'bg-slate-400'}`}
                  />
                  {tenant.status === 'active' ? 'Active' : 'Inactive'}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-8">
          <nav className="flex items-center gap-6" aria-label="Tabs">
            <Link
              to="/tenants/$tenantId"
              params={{ tenantId }}
              activeOptions={{ exact: true }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-2 font-medium text-sm transition-colors border-transparent text-slate-500 hover:text-slate-700 data-[status=active]:border-indigo-600 data-[status=active]:text-indigo-600"
            >
              <Building2 className="w-4 h-4" />
              Overview
            </Link>
            <Link
              to="/tenants/$tenantId/users"
              params={{ tenantId }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-2 font-medium text-sm transition-colors border-transparent text-slate-500 hover:text-slate-700 data-[status=active]:border-indigo-600 data-[status=active]:text-indigo-600"
            >
              <Users className="w-4 h-4" />
              Users
            </Link>
            <Link
              to="/tenants/$tenantId/apps"
              params={{ tenantId }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-2 font-medium text-sm transition-colors border-transparent text-slate-500 hover:text-slate-700 data-[status=active]:border-indigo-600 data-[status=active]:text-indigo-600"
            >
              <Box className="w-4 h-4" />
              Apps
            </Link>

            {/* Developer Section */}
            <div className="flex items-center gap-4 ml-6 pl-6 border-l border-slate-200">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Code2 className="w-3.5 h-3.5" />
                Developer
              </span>
              <Link
                to="/tenants/$tenantId/api-tokens"
                params={{ tenantId }}
                className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-2 font-medium text-sm transition-colors border-transparent text-slate-500 hover:text-slate-700 data-[status=active]:border-indigo-600 data-[status=active]:text-indigo-600"
              >
                <Key className="w-4 h-4" />
                API Tokens
              </Link>
              <Link
                to="/tenants/$tenantId/webhooks"
                params={{ tenantId }}
                className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-2 font-medium text-sm transition-colors border-transparent text-slate-500 hover:text-slate-700 data-[status=active]:border-indigo-600 data-[status=active]:text-indigo-600"
              >
                <Network className="w-4 h-4" />
                Webhooks
              </Link>
            </div>
          </nav>
        </div>
      </div>

      <div className="flex-1 max-w-7xl mx-auto w-full p-8">
        <Outlet />
      </div>
    </div>
  );
}
