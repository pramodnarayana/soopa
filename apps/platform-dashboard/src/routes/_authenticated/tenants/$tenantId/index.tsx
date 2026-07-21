import { createFileRoute } from '@tanstack/react-router';

import { useState, useEffect } from 'react';
import { useGetTenants } from '@/domains/tenants/api/queries';
import { useUpdateTenantName } from '@/domains/tenants/api/mutations';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

export const Route = createFileRoute('/_authenticated/tenants/$tenantId/')({
  component: TenantOverviewPage,
});

function TenantOverviewPage() {
  const { tenantId } = Route.useParams();

  
  const { data: tenants = [] } = useGetTenants();

  const tenant = tenants.find((t: any) => t.id === tenantId);
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
        onError: (err: any) => {
          toast.error(err.message || 'Failed to update tenant name');
        }
      }
    );
  };

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
    </div>
  );
}
