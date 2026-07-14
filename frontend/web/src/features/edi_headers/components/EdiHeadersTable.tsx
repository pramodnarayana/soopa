import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Network } from 'lucide-react';
import type { EdiHeaderItem } from '../types';
import { useEdiHeaders } from '../api/ediHeadersApi';
import { EdiHeaderDetails } from './EdiHeaderDetails';
import { DataTable } from '@/components/ui/data-table';

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
];

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
