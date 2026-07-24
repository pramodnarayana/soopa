import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { createColumnHelper, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Building2, Loader2, Plus, Power, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useDeleteTenant,
  useProvisionTenant,
  useUpdateTenantStatus,
} from '@/domains/tenants/api/mutations';
import { useGetTenants } from '@/domains/tenants/api/queries';

interface Tenant {
  id: string;
  name: string;
  status: TenantStatus;
  createdAt: string;
  updatedAt: string;
}

const TENANT_STATUS = {
  ACTIVE: 'active',
  INACTIVE: 'inactive',
} as const;

type TenantStatus = (typeof TENANT_STATUS)[keyof typeof TENANT_STATUS];

const STATUS_THEME = {
  [TENANT_STATUS.ACTIVE]: {
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    dot: 'bg-emerald-500',
    toggleBg: 'bg-emerald-50 border-emerald-200',
    toggleText: 'text-emerald-700',
    toggleSwitch: 'translate-x-[62px] bg-emerald-600 text-white',
    icon: 'text-white',
  },
  [TENANT_STATUS.INACTIVE]: {
    badge: 'bg-slate-50 text-slate-700 border-slate-200',
    dot: 'bg-slate-400',
    toggleBg: 'bg-slate-100 border-slate-300',
    toggleText: 'text-slate-500',
    toggleSwitch: 'translate-x-0 bg-white text-slate-400',
    icon: 'text-slate-400',
  },
  unknown: {
    badge: 'bg-amber-50 text-amber-700 border-amber-200',
    dot: 'bg-amber-500',
    toggleBg: 'bg-slate-100 border-slate-300',
    toggleText: 'text-slate-500',
    toggleSwitch: 'translate-x-0 bg-white text-slate-400',
    icon: 'text-slate-400',
  },
} as const;

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
        },
      },
    );
  };

  const columns = React.useMemo(
    () => [
      columnHelper.accessor('name', {
        header: 'Tenant Name',
        cell: (info) => (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
              <Building2 className="w-4 h-4" />
            </div>
            <span className="font-medium text-sm text-slate-900">{info.getValue()}</span>
          </div>
        ),
      }),
      columnHelper.accessor('status', {
        header: 'Status',
        cell: (info) => {
          const status = info.getValue();
          const isActive = status === TENANT_STATUS.ACTIVE;
          const theme = STATUS_THEME[status as keyof typeof STATUS_THEME] ?? STATUS_THEME.unknown;
          const displayText = isActive
            ? 'Active'
            : status === TENANT_STATUS.INACTIVE
              ? 'Inactive'
              : 'Unknown';
          return (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${theme.badge}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${theme.dot}`} />
              {displayText}
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
              day: 'numeric',
            })}
          </span>
        ),
      }),
      columnHelper.display({
        id: 'actions',
        cell: (info) => {
          const tenant = info.row.original;
          const status = tenant.status;
          const isActive = status === TENANT_STATUS.ACTIVE;
          const isInactive = status === TENANT_STATUS.INACTIVE;
          const isKnownStatus = isActive || isInactive;
          const theme = STATUS_THEME[status as keyof typeof STATUS_THEME] ?? STATUS_THEME.unknown;

          return (
            <div className="flex justify-end pr-4">
              <Button
                variant="outline"
                size="sm"
                className="text-indigo-600 border-indigo-200 hover:bg-indigo-50 mr-4"
                onClick={(e) => {
                  e.stopPropagation();
                  void navigate({ to: `/tenants/${tenant.id}` });
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
                    if (isKnownStatus) {
                      statusMutation.mutate({
                        id: tenant.id,
                        status: isActive ? TENANT_STATUS.INACTIVE : TENANT_STATUS.ACTIVE,
                      });
                    }
                  }}
                  disabled={statusMutation.isPending || !isKnownStatus}
                  title={
                    !isKnownStatus
                      ? 'Unknown status - toggle disabled'
                      : isActive
                        ? 'Deactivate Tenant'
                        : 'Activate Tenant'
                  }
                  aria-label={
                    !isKnownStatus
                      ? 'Unknown status - toggle disabled'
                      : isActive
                        ? 'Deactivate Tenant'
                        : 'Activate Tenant'
                  }
                  className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${theme.toggleBg} ${statusMutation.isPending || !isKnownStatus ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <span
                    className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-100 ' + theme.toggleText : 'opacity-0'}`}
                  >
                    Active
                  </span>
                  <span
                    className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-0' : 'opacity-100 ' + theme.toggleText}`}
                  >
                    Inactive
                  </span>
                  <span
                    aria-hidden="true"
                    className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${theme.toggleSwitch}`}
                  >
                    {statusMutation.isPending ? (
                      <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
                    ) : (
                      <Power className={`w-3 h-3 ${theme.icon}`} />
                    )}
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
                  if (
                    confirm(
                      'Are you sure you want to completely delete this tenant? This action cannot be undone.',
                    )
                  ) {
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
    ],
    [statusMutation, deleteMutation, navigate],
  );

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
          <DialogTrigger
            render={
              <Button className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm gap-2 rounded-xl h-10 px-5" />
            }
          >
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
                  <Label htmlFor="name" className="text-slate-700">
                    Company Name
                  </Label>
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
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Provisioning
                    </>
                  ) : (
                    'Provision Tenant'
                  )}
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
          onRowClick={(row) => {
            void navigate({ to: `/tenants/${row.original.id}` });
          }}
        />
      </div>
    </div>
  );
}
