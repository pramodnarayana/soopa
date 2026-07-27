import { DashboardProvider, EdiDashboardPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useUpdateTenantName } from '@/domains/tenants/api/mutations';
import { useGetTenants } from '@/domains/tenants/api/queries';
import { HttpDashboardRepository } from '@/lib/HttpDashboardRepository';

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantId/')({
  component: TenantOverviewPage,
});

function TenantOverviewPage() {
  const { tenantId } = Route.useParams();

  const { data: tenants = [] } = useGetTenants();

  const tenant = tenants.find((t: { id: string; name: string }) => t.id === tenantId);
  const [name, setName] = useState('');

  useEffect(() => {
    if (tenant) setName(tenant.name);
  }, [tenant]);

  const updateNameMutationObj = useUpdateTenantName();

  const handleUpdateName = (newName: string) => {
    updateNameMutationObj.mutate(
      { id: tenantId, name: newName },
      {
        onSuccess: () => {
          toast.success('Tenant name updated successfully');
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to update tenant name');
        },
      },
    );
  };

  const dashboardRepository = useMemo(() => {
    return new HttpDashboardRepository(tenantId);
  }, [tenantId]);

  if (!tenant) return null;

  return (
    <div className="bg-white rounded-2xl border border-slate-200/60 shadow-sm p-8 max-w-2xl">
      <h2 className="text-lg font-semibold text-slate-900 mb-6">Tenant Overview</h2>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label className="text-slate-700">Company Name</Label>
          <div className="flex gap-3">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="rounded-lg bg-white"
            />
            <Button
              variant="outline"
              className="rounded-lg shrink-0"
              disabled={name === tenant.name || updateNameMutationObj.isPending || !name.trim()}
              onClick={() => handleUpdateName(name)}
            >
              {updateNameMutationObj.isPending ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </div>
      </div>

      <div className="mt-12">
        <h2 className="text-lg font-semibold text-slate-900 mb-6">EDI Network Isolation</h2>
        <DashboardProvider repository={dashboardRepository}>
          <EdiDashboardPage />
        </DashboardProvider>
      </div>
    </div>
  );
}
