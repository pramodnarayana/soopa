import { Badge, Card, CardContent, CardHeader, CardTitle } from '@soopa/ui';
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
      <section className="flex flex-col gap-1 pb-6 border-b border-border">
        <h2 className="text-3xl font-bold tracking-tight text-foreground flex items-center gap-3">
          <LayoutDashboard className="w-8 h-8 text-primary" />
          Dashboard
        </h2>
        <p className="text-muted-foreground text-sm">Welcome back, {tenant?.name}.</p>
      </section>

      {/* Active Modules */}
      <Card>
        <CardHeader>
          <CardTitle>Active Modules</CardTitle>
        </CardHeader>
        <CardContent>
          {activeSubscriptions.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              No active subscriptions. Contact your administrator.
            </p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {activeSubscriptions.map((app) => (
                <Badge key={app} variant="secondary">
                  {app.toUpperCase()}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
