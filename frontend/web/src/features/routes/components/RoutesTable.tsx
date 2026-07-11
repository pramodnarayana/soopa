
import {
  createColumnHelper,

  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import type { RouteItem } from '../types';
import { Network, ArrowRightLeft, ArrowLeftRight } from 'lucide-react';
import { DataTable } from '@/components/ui/data-table';
import { SharedRowActions } from '@/features/partners/components/SharedRowActions';
import { useUpdateRouteMutation, useDeleteRouteMutation } from '../api/routeHooks';
import { useToast } from '@/hooks/use-toast';
import { RouteDetails } from './RouteDetails';

const columnHelper = createColumnHelper<RouteItem>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Route Name',
    cell: (info) => (
      <div className="flex flex-col gap-1">
        <span className="font-medium text-slate-900">
          {info.getValue()}
        </span>
        {info.row.original.trading_partner_id && (
          <div className="text-xs text-slate-400 mt-1">
            Trading Partner ID: {info.row.original.trading_partner_id}
          </div>
        )}
      </div>
    ),
  }),
  columnHelper.accessor('direction', {
    header: 'Direction',
    cell: (info) => {
      const isOutbound = info.getValue() === 'OUTBOUND';
      return (
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${!isOutbound
            ? 'bg-blue-50 text-blue-600 border border-blue-100'
            : 'bg-emerald-50 text-emerald-600 border border-emerald-100'
            }`}>
            {isOutbound ? <ArrowLeftRight className="w-4 h-4" /> : <ArrowRightLeft className="w-4 h-4" />}
          </div>
          <span className="font-semibold text-slate-900">
            {isOutbound ? 'From JSON' : 'From EDI'}
          </span>
        </div>
      );
    },
  }),
  columnHelper.accessor('transaction_type', {
    header: 'Transaction',
    cell: (info) => {
      const val = info.getValue();
      const displayVal = !val || val === '*' ? 'All' : val;
      return (
        <span className="font-mono text-sm px-2 py-1 bg-slate-100 rounded-md text-slate-600 border border-slate-200">
          {displayVal}
        </span>
      );
    },
  }),
  columnHelper.accessor('processing_mode', {
    header: 'Mode',
    cell: (info) => (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
        info.getValue() === 'TRANSLATE'
          ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
          : 'bg-amber-50 text-amber-700 border-amber-200'
      }`}>
        {info.getValue() === 'TRANSLATE' ? 'Translate' : 'Passthrough'}
      </span>
    ),
  }),
  columnHelper.accessor('isa_sender_id', {
    header: 'ISA Routing',
    cell: (info) => (
      <div className="flex items-center gap-2 text-sm text-slate-600 font-medium">
        <span className="px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200">{info.getValue()}</span>
        <span className="text-slate-300">→</span>
        <span className="px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200">{info.row.original.isa_receiver_id}</span>
      </div>
    ),
  }),
  columnHelper.accessor('destination_name', {
    header: 'Target Destination',
    cell: (info) => (
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded uppercase tracking-wider">
          {info.row.original.destination_type}
        </span>
        <span className="text-sm text-slate-900 font-medium truncate max-w-[150px] lg:max-w-[200px]" title={info.getValue()}>
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
        <RouteRowActions route={info.row.original} />
      </div>
    ),
  }),
];

function RouteRowActions({ route }: { route: RouteItem }) {
  const updateMutation = useUpdateRouteMutation();
  const deleteMutation = useDeleteRouteMutation();
  const { toast } = useToast();

  const handleToggle = () => {
    updateMutation.mutate(
      { routeId: route.route_id, direction: route.direction, payload: { active: !route.active } },
      {
        onSuccess: () => {
          toast({
            title: `Route ${!route.active ? 'Activated' : 'Deactivated'}`,
            description: `The route for ${route.transaction_type} has been ${!route.active ? 'activated' : 'deactivated'}.`
          });
        },
        onError: (err) => {
          toast({
            title: 'Error',
            description: err.message || 'Failed to update route',
            variant: 'destructive',
          });
        }
      }
    );
  };

  const handleDelete = () => {
    if (!confirm(`Are you sure you want to delete this route?`)) return;
    deleteMutation.mutate(
      { routeId: route.route_id, direction: route.direction },
      {
        onSuccess: () => {
          toast({
            title: 'Route Deleted',
            description: 'The route has been permanently removed.'
          });
        },
        onError: (err) => {
          toast({
            title: 'Error',
            description: err.message || 'Failed to delete route',
            variant: 'destructive',
          });
        }
      }
    );
  };

  return (
    <SharedRowActions
      isActive={route.active}
      isUpdating={updateMutation.isPending}
      isDeleting={deleteMutation.isPending}
      onToggleActive={handleToggle}
      onDelete={handleDelete}
      entityName="Route"
    />
  );
}

export function RoutesTable({ data, isLoading }: { data: RouteItem[]; isLoading: boolean }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      dataLength={data.length}
      emptyIcon={<Network className="w-8 h-8" />}
      emptyTitle="No Active Routes"
      columnsLength={columns.length}
      renderExpandedRow={(row) => <RouteDetails route={row.original} onCancel={() => row.toggleExpanded()} />}
    />
  );
}
