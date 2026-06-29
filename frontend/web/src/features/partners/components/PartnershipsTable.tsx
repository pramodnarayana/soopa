import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import type { Partnership } from '../context/PlatformPartnersContext';
import { MoreHorizontal, Network, Plus, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Link } from '@tanstack/react-router';

const columnHelper = createColumnHelper<Partnership>();

const columns = [
  columnHelper.accessor('id', {
    header: 'Partnership',
    cell: (info) => (
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600">
          <Network className="w-4 h-4" />
        </div>
        <span className="font-semibold text-slate-900 font-mono text-xs">
          {info.getValue().substring(0, 8)}...
        </span>
      </div>
    ),
  }),
  columnHelper.accessor('host', {
    header: 'Host & Port',
    cell: (info) => {
      const host = info.row.original.host;
      const port = info.row.original.port;
      if (!host) return <span className="text-slate-400 text-sm">N/A</span>;
      return (
        <span className="font-mono text-sm text-slate-600">
          {host}:{port}
        </span>
      );
    },
  }),
  columnHelper.accessor('mdn_type', {
    header: 'MDN Type',
    cell: (info) => (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('encryption_algorithm', {
    header: 'Security',
    cell: (info) => (
      <div className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
          Enc: {info.getValue()}
        </span>
        <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <ShieldCheck className="w-3.5 h-3.5 text-indigo-500" />
          Sig: {info.row.original.signature_algorithm}
        </span>
      </div>
    ),
  }),
  columnHelper.display({
    id: 'actions',
    cell: () => (
      <div className="flex justify-end">
        <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 hover:text-slate-900">
          <MoreHorizontal className="w-4 h-4" />
        </Button>
      </div>
    ),
  }),
];

export function PartnershipsTable({ data, isLoading, scope = 'tenant' }: { data: Partnership[]; isLoading: boolean; scope?: 'platform' | 'tenant' }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (isLoading) {
    return (
      <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden flex flex-col">
        <div className="p-6 border-b border-slate-100/50 flex justify-between items-center">
          <div>
            <div className="h-6 w-48 bg-slate-100 rounded-md animate-pulse mb-2" />
            <div className="h-4 w-64 bg-slate-100 rounded-md animate-pulse" />
          </div>
        </div>
        <div className="p-8">
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="h-12 w-full bg-slate-50 rounded-xl animate-pulse" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden">
        <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
          <div className="w-16 h-16 bg-slate-50 border border-slate-100 rounded-2xl flex items-center justify-center text-slate-300 mb-6 shadow-sm">
            <Network className="w-8 h-8" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">No AS2 Partnerships Found</h3>
          <p className="text-slate-500 max-w-sm mb-6 leading-relaxed">
            There are currently no active AS2 partnerships configured for this {scope}. Get started by setting up a connection between a local and remote station.
          </p>
          <Link to={scope === 'platform' ? '/platform/partners' : '/tenant/partners'}>
            <Button className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-sm">
              <Plus className="w-4 h-4 mr-2" />
              Configure Partnership
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-slate-200/60 bg-slate-50/50">
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-slate-50/50 transition-colors group">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-6 py-4">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
