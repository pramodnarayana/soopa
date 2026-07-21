import { createFileRoute, useNavigate } from '@tanstack/react-router';

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { createColumnHelper, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useGetTenants } from '@/domains/tenants/api/queries';
import { useProvisionTenant, useUpdateTenantStatus, useDeleteTenant } from '@/domains/tenants/api/mutations';
import { Building2, Plus, Trash2, Power, Loader2 } from 'lucide-react';

interface Tenant {
  id: string;
  name: string;
  status: 'active' | 'inactive';
  createdAt: string;
  updatedAt: string;
}

const columnHelper = createColumnHelper<Tenant>();

export const Route = createFileRoute('/_authenticated/tenants/')({
  component: TenantsPage,
});

function TenantsPage() {
  const navigate = useNavigate();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [formData, setFormData] = useState({ name: '' });

  const { data: tenants = [], isLoading } = useGetTenants();
  const provisionMutation = useProvisionTenant();
  const statusMutation = useUpdateTenantStatus();
  const deleteMutation = useDeleteTenant();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    provisionMutation.mutate(
      { name: formData.name },
      {
        onSuccess: () => {
          setIsDialogOpen(false);
          setFormData({ name: '' });
        }
      }
    );
  };

  const columns = React.useMemo(() => [
    columnHelper.accessor('name', {
      header: 'Tenant Name',
      cell: (info) => (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
            <Building2 className="w-4 h-4" />
          </div>
          <span className="font-medium text-sm text-slate-900">
            {info.getValue()}
          </span>
        </div>
      ),
    }),
    columnHelper.accessor('status', {
      header: 'Status',
      cell: (info) => {
        const isActive = info.getValue() === 'active';
        return (
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${isActive ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-700 border-slate-200'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${isActive ? 'bg-emerald-500' : 'bg-slate-400'}`} />
            {isActive ? 'Active' : 'Inactive'}
          </span>
        );
      },
    }),
    columnHelper.accessor('createdAt', {
      header: 'Provisioned On',
      cell: (info) => (
        <span className="text-slate-500 text-sm">
          {new Date(info.getValue()).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
          })}
        </span>
      ),
    }),
    columnHelper.display({
      id: 'actions',
      cell: (info) => {
        const tenant = info.row.original;
        const isActive = tenant.status === 'active';
        
        return (
          <div className="flex justify-end pr-4">
            <Button
              variant="outline"
              size="sm"
              className="text-indigo-600 border-indigo-200 hover:bg-indigo-50 mr-4"
              onClick={(e) => {
                e.stopPropagation();
                navigate({ to: `/tenants/${tenant.id}` });
              }}
            >
              Manage
            </Button>
            <div className="flex items-center gap-4 mr-2" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                role="switch"
                aria-checked={isActive}
                onClick={(e) => {
                  e.stopPropagation();
                  statusMutation.mutate({ id: tenant.id, status: isActive ? 'inactive' : 'active' })
                }}
                disabled={statusMutation.isPending}
                title={isActive ? 'Deactivate Tenant' : 'Activate Tenant'}
                aria-label={isActive ? 'Deactivate Tenant' : 'Activate Tenant'}
                className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${isActive ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-100 border-slate-300'} ${statusMutation.isPending ? 'opacity-50 cursor-wait' : ''}`}
              >
                <span
                  className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-100 text-emerald-700' : 'opacity-0'}`}
                >
                  Active
                </span>
                <span
                  className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-0' : 'opacity-100 text-slate-500'}`}
                >
                  Inactive
                </span>
                <span
                  aria-hidden="true"
                  className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${isActive ? 'translate-x-[62px] bg-emerald-600 text-white' : 'translate-x-0 bg-white text-slate-400'}`}
                >
                  {statusMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin text-slate-400" /> : <Power className={`w-3 h-3 ${isActive ? 'text-white' : 'text-slate-400'}`} />}
                </span>
              </button>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="text-slate-400 hover:text-red-600 hover:bg-red-50"
              disabled={deleteMutation.isPending}
              onClick={(e) => {
                e.stopPropagation();
                if (confirm('Are you sure you want to completely delete this tenant? This action cannot be undone.')) {
                  deleteMutation.mutate(tenant.id);
                }
              }}
              title="Delete Tenant"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        );
      },
    }),
  ], [statusMutation, deleteMutation, navigate]);

  const table = useReactTable({
    data: tenants,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight">Tenants</h1>
          <p className="text-slate-500 mt-1">Manage and provision organizations on the platform.</p>
        </div>
        
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger render={<Button className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm gap-2 rounded-xl h-10 px-5" />}>
              <Plus className="w-4 h-4" />
              Provision Tenant
          </DialogTrigger>
          <DialogContent className="sm:max-w-[425px]">
            <form onSubmit={handleSubmit}>
              <DialogHeader>
                <DialogTitle>Provision New Tenant</DialogTitle>
                <DialogDescription>
                  Enter the details for the new organization to provision their infrastructure.
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-6">
                <div className="flex flex-col gap-3">
                  <Label htmlFor="name" className="text-slate-700">Company Name</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="Acme Corp"
                    className="col-span-3 rounded-lg"
                    required
                  />
                </div>
              </div>
              <DialogFooter>
                <Button 
                  type="button" 
                  variant="outline" 
                  onClick={() => setIsDialogOpen(false)}
                  className="rounded-lg"
                >
                  Cancel
                </Button>
                <Button 
                  type="submit"
                  disabled={provisionMutation.isPending || !formData.name.trim()}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg min-w-[120px]"
                >
                  {provisionMutation.isPending ? (
                    <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Provisioning</>
                  ) : 'Provision Tenant'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="bg-white border border-slate-200 shadow-sm rounded-2xl overflow-hidden">
        <DataTable
          table={table}
          columnsLength={columns.length}
          isLoading={isLoading}
          dataLength={tenants.length}
          emptyIcon={<Building2 className="w-8 h-8" />}
          emptyTitle="No Tenants Provisioned"
          emptyDescription="Get started by provisioning your first tenant."
          onRowClick={(row) => navigate({ to: `/tenants/${row.original.id}` })}
        />
      </div>
    </div>
  );
}
