import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { createFileRoute, notFound } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useUpdateTenantName } from '@/domains/tenants/api/mutations';
import { type Tenant, useGetTenants } from '@/domains/tenants/api/queries';

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantSlug/')({
  component: TenantOverviewPage,
});

function TenantOverviewPage() {
  const { tenantSlug } = Route.useParams();

  const { data: tenants = [], isLoading } = useGetTenants();

  const tenant = tenants.find((t: Tenant) => t.slug === tenantSlug);

  const [name, setName] = useState('');

  useEffect(() => {
    if (tenant) setName(tenant.name);
  }, [tenant]);

  const updateNameMutationObj = useUpdateTenantName();

  const handleUpdateName = (newName: string) => {
    if (!tenant) return;
    updateNameMutationObj.mutate(
      { id: tenant.id, name: newName },
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

  if (!isLoading && !tenant) throw notFound();
  if (!tenant) return null;

  return (
    <div className="bg-card rounded-2xl border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] p-8">
      <div className="flex justify-between items-center mb-8">
        <h2 className="text-2xl font-bold tracking-tight text-foreground">Tenant Overview</h2>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={name === tenant.name || updateNameMutationObj.isPending}
            onClick={() => setName(tenant.name)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={name === tenant.name || updateNameMutationObj.isPending || !name.trim()}
            onClick={() => handleUpdateName(name)}
          >
            {updateNameMutationObj.isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      <div className="space-y-4 max-w-2xl">
        <div className="space-y-2">
          <Label>Company Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      </div>
    </div>
  );
}
