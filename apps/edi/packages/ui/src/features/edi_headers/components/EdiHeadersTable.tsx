import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Network } from 'lucide-react';
import type { EdiHeaderItem } from '../types';
import { EdiHeaderDetails } from './EdiHeaderDetails';
import { DataTable } from '@/components/ui/data-table';
import { useEdiHeaders, useDeleteEdiHeaderMutation } from '../api/ediHeadersApi';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';

const columnHelper = createColumnHelper<EdiHeaderItem>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Name',
    cell: (info) => (
      <span className="font-medium text-slate-900">{info.getValue()}</span>
    ),
  }),
  columnHelper.accessor('trading_partner_id', {
    header: 'Trading Partner',
    cell: (info) => (
      <span className="font-mono text-sm px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-slate-700 uppercase">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('transaction_type', {
    header: 'Transaction',
    cell: (info) => {
      const val = info.getValue();
      const displayVal = !val || val === '*' ? 'All' : val;
      return (
        <span className="font-mono text-sm px-2 py-1 bg-indigo-50 rounded-md text-indigo-700 border border-indigo-200">
          {displayVal}
        </span>
      );
    },
  }),
  columnHelper.accessor('isa_sender_id', {
    header: 'ISA Sender',
    cell: (info) => (
      <span className="font-mono text-sm px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-slate-700">
        {info.getValue() || <span className="text-slate-300 italic">—</span>}
      </span>
    ),
  }),
  columnHelper.accessor('isa_receiver_id', {
    header: 'ISA Receiver',
    cell: (info) => (
      <span className="font-mono text-sm px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-slate-700">
        {info.getValue() || <span className="text-slate-300 italic">—</span>}
      </span>
    ),
  }),
  columnHelper.accessor('gs_sender_id', {
    header: 'GS Sender',
    cell: (info) => (
      <span className="font-mono text-sm px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-slate-700">
        {info.getValue() || <span className="text-slate-300 italic">—</span>}
      </span>
    ),
  }),
  columnHelper.accessor('gs_receiver_id', {
    header: 'GS Receiver',
    cell: (info) => (
      <span className="font-mono text-sm px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-slate-700">
        {info.getValue() || <span className="text-slate-300 italic">—</span>}
      </span>
    ),
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <EdiHeaderRowActions header={info.row.original} />
      </div>
    ),
  }),
];

function EdiHeaderRowActions({ header }: { header: EdiHeaderItem }) {
  const deleteMutation = useDeleteEdiHeaderMutation();
  const { toast } = useToast();

  const handleDelete = () => {
    if (!confirm(`Are you sure you want to delete this EDI Header?`)) return;
    deleteMutation.mutate(header.id, {
      onSuccess: () => {
        toast({
          title: 'EDI Header Deleted',
          description: 'The EDI Header has been successfully deleted.',
        });
      },
      onError: (err) => {
        toast({
          title: 'Error',
          description: err.message || 'Failed to delete EDI Header',
          variant: 'destructive',
        });
      }
    });
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 w-8 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
      onClick={handleDelete}
      disabled={deleteMutation.isPending}
    >
      <span className="sr-only">Delete</span>
      <Trash2 className="h-4 w-4" />
    </Button>
  );
}

export function EdiHeadersTable() {
  const { data: headers, isLoading } = useEdiHeaders();

  const table = useReactTable({
    data: headers || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  return (
    <div className="space-y-4">
      <DataTable
        table={table}
        isLoading={isLoading}
        dataLength={headers?.length || 0}
        emptyIcon={<Network className="w-8 h-8 text-slate-300" />}
        emptyTitle="No EDI Headers"
        columnsLength={columns.length}
        renderExpandedRow={(row) => <EdiHeaderDetails header={row.original} onCancel={() => row.toggleExpanded()} />}
      />
    </div>
  );
}
