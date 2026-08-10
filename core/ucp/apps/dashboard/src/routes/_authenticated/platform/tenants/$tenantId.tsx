import { Skeleton } from '@soopa/ui/components/ui/skeleton';
import { createFileRoute, Link, Outlet } from '@tanstack/react-router';
import { ArrowLeft, Box, Building2, Users } from 'lucide-react';
import { useGetTenants } from '@/domains/tenants/api/queries';

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantId')({
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
      <div className="w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out fill-mode-both">
        <Skeleton className="h-10 w-48 rounded-lg" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (!tenant) {
    return <div className="p-8">Tenant not found</div>;
  }

  return (
    <div className="flex flex-col min-h-full animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out fill-mode-both">
      <div className="bg-card border-b border-border shadow-[0_2px_8px_rgb(0,0,0,0.02)]">
        <div className="w-full pb-6">
          <div className="mb-6">
            <Link
              to="/platform/tenants"
              className="inline-flex items-center text-sm font-medium text-muted-foreground hover:text-primary transition-colors"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back to Tenants
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center text-primary border border-primary/20">
              <Building2 className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-[28px] font-bold text-foreground tracking-tight">
                {tenant.name}
              </h1>
              <div className="flex items-center gap-2 mt-2">
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-widest border ${tenant.status === 'active' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-700 border-slate-200'}`}
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
        <div className="w-full">
          <nav className="flex items-center gap-8" aria-label="Tabs">
            <Link
              to="/platform/tenants/$tenantId"
              params={{ tenantId }}
              activeOptions={{ exact: true }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-[3px] font-semibold text-[15px] transition-colors border-transparent text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-primary"
            >
              <Building2 className="w-4 h-4" />
              Overview
            </Link>
            <Link
              to="/platform/tenants/$tenantId/users"
              params={{ tenantId }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-[3px] font-semibold text-[15px] transition-colors border-transparent text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-primary"
            >
              <Users className="w-4 h-4" />
              Users
            </Link>
            <Link
              to="/platform/tenants/$tenantId/apps"
              params={{ tenantId }}
              className="group inline-flex items-center gap-2 pb-4 pt-2 border-b-[3px] font-semibold text-[15px] transition-colors border-transparent text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-primary"
            >
              <Box className="w-4 h-4" />
              Apps
            </Link>
          </nav>
        </div>
      </div>

      <div className="flex-1 w-full pt-8">
        <Outlet />
      </div>
    </div>
  );
}
