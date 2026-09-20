import { type FieldDef, QueryBuilder, useClientFilter } from '@soopa/ui';
import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { ArrowLeftRight, Network } from 'lucide-react';
import { SharedRowActions } from '../../../features/partners/components/SharedRowActions';
import { useToast } from '../../../hooks/use-toast';
import {
  useDeleteOutboundRouteMutation,
  useUpdateOutboundRouteMutation,
} from '../api/outboundRouteHooks';
import type { OutboundRouteItem } from '../types';
import { OutboundRouteDetails } from './OutboundRouteDetails';

const columnHelper = createColumnHelper<OutboundRouteItem>();

const columns = [
  columnHelper.accessor('trading_partner_id', {
    header: 'Trading Partner',
    cell: (info) => {
      const val = info.getValue();
      if (!val) {
        return <span className="text-slate-500 italic">No Trading Partner Assigned</span>;
      }
      return (
        <span className="flex items-center gap-2">
          <span className="w-6 h-6 rounded bg-emerald-100 flex items-center justify-center text-emerald-700">
            <Network className="w-3.5 h-3.5" />
          </span>
          {val}
        </span>
      );
    },
  }),
  columnHelper.accessor('name', {
    header: 'Route Name',
    cell: (info) => <span className="font-medium text-slate-900">{info.getValue()}</span>,
  }),
  columnHelper.accessor('destination_name', {
    header: 'Target Destination',
    cell: (info) => (
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded uppercase tracking-wider">
          {info.row.original.destination_type}
        </span>
        <span
          className="text-sm text-slate-900 font-medium truncate max-w-[150px] lg:max-w-[200px]"
          title={info.getValue()}
        >
          {info.getValue()}
        </span>
      </div>
    ),
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <RowActions route={info.row.original} />
      </div>
    ),
  }),
];

function RowActions({ route }: { route: OutboundRouteItem }) {
  const updateMutation = useUpdateOutboundRouteMutation();
  const deleteMutation = useDeleteOutboundRouteMutation();
  const { toast } = useToast();

  const handleToggle = () => {
    updateMutation.mutate(
      { routeId: route.route_id, payload: { active: !route.active } },
      {
        onSuccess: () => {
          toast({
            title: `Route ${!route.active ? 'Activated' : 'Deactivated'}`,
            description: `Outbound route "${route.name}" has been ${!route.active ? 'activated' : 'deactivated'}.`,
          });
        },
        onError: (err) => {
          toast({
            title: 'Error',
            description: err.message || 'Failed to update route',
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleDelete = () => {
    if (!confirm('Are you sure you want to delete this outbound route?')) return;
    deleteMutation.mutate(route.route_id, {
      onSuccess: () => toast({ title: 'Route Deleted', description: 'Outbound route removed.' }),
      onError: (err) =>
        toast({
          title: 'Error',
          description: err.message || 'Failed to delete route',
          variant: 'destructive',
        }),
    });
  };

  return (
    <SharedRowActions
      isActive={route.active}
      isUpdating={updateMutation.isPending}
      isDeleting={deleteMutation.isPending}
      onToggleActive={handleToggle}
      onDelete={handleDelete}
      entityName="Outbound Route"
    />
  );
}

const availableFields: FieldDef[] = [
  { id: 'trading_partner_id', label: 'Trading Partner', type: 'text' },
  { id: 'name', label: 'Route Name', type: 'text' },
  { id: 'destination_name', label: 'Destination', type: 'text' },
];

export function OutboundRoutesTable({
  data: rawData,
  isLoading,
}: {
  data: OutboundRouteItem[];
  isLoading: boolean;
}) {
  const { filters, setFilters, filteredData: data } = useClientFilter(rawData);

  const table = useReactTable({
    data,
    columns,
    initialState: { sorting: [{ id: 'trading_partner_id', desc: false }] },
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowCanExpand: () => true,
  });

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <QueryBuilder fields={availableFields} rules={filters} onChange={setFilters} />
      </div>
      <DataTable
        table={table}
        columnsLength={columns.length}
        isLoading={isLoading}
        dataLength={data.length}
        emptyIcon={<ArrowLeftRight className="w-8 h-8" />}
        emptyTitle="No Outbound Routes Configured"
        emptyDescription="Get started by creating your first outbound route."
        renderExpandedRow={(row) => (
          <OutboundRouteDetails route={row.original} onCancel={() => row.toggleExpanded()} />
        )}
        getGroupBoundary={(row, prevRow) =>
          row.original.trading_partner_id !== prevRow.original.trading_partner_id
        }
      />
    </div>
  );
}
