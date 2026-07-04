import {
  createColumnHelper,

  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import type { Endpoint } from '../types';
import { Network } from 'lucide-react';
import { DataTable } from '@/components/ui/data-table';

const columnHelper = createColumnHelper<Endpoint>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Name',
    cell: (info) => (
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
          <Network className="w-4 h-4" />
        </div>
        <span className="font-semibold text-slate-900">{info.getValue()}</span>
      </div>
    ),
  }),
  columnHelper.accessor('type', {
    header: 'Type',
    cell: (info) => (
      <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-700">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => (
      <span
        className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
          info.getValue() === 'ACTIVE'
            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/50'
            : 'bg-slate-100 text-slate-700 border border-slate-200/50'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${info.getValue() === 'ACTIVE' ? 'bg-emerald-500' : 'bg-slate-400'}`} />
        {info.getValue()}
      </span>
    ),
  }),
];

interface EndpointsTableProps {
  data: Endpoint[];
  isLoading: boolean;
}

export function EndpointsTable({ data, isLoading }: EndpointsTableProps) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      dataLength={data.length}
      emptyIcon={<Network className="w-8 h-8" />}
      emptyTitle="No endpoints found"
      columnsLength={columns.length}

    />
  );
}
