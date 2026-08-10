import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useUpdateTenantName } from '@/domains/tenants/api/mutations';
import { useGetTenants } from '@/domains/tenants/api/queries';

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

  if (!tenant) return null;

  return (
    <div className="bg-card rounded-2xl border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] p-8">
      <div className="flex justify-between items-center mb-8">
        <h2 className="text-2xl font-bold tracking-tight text-foreground">Tenant Overview</h2>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            className="rounded-xl h-10 px-5 text-[14px] font-semibold"
            disabled={name === tenant.name || updateNameMutationObj.isPending}
            onClick={() => setName(tenant.name)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-10 px-5 text-[14px] font-semibold min-w-[80px]"
            disabled={name === tenant.name || updateNameMutationObj.isPending || !name.trim()}
            onClick={() => handleUpdateName(name)}
          >
            {updateNameMutationObj.isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      <div className="space-y-4 max-w-2xl">
        <div className="space-y-2">
          <Label className="text-sm font-medium text-muted-foreground">Company Name</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-11 rounded-xl bg-background"
          />
        </div>
      </div>
    </div>
  );
}
