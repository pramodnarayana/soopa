import React from 'react';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  getExpandedRowModel,
} from '@tanstack/react-table';
import type { Partnership } from '../context/PlatformPartnersContext';
import { Network, ShieldCheck } from 'lucide-react';
import { PartnershipDetails } from './PartnershipDetails';
import { SharedRowActions } from './SharedRowActions';
import { useUpdatePlatformPartnershipMutation, useDeletePlatformPartnershipMutation } from '../api/partnerHooks';

function PartnershipRowActions({ partnership }: { partnership: Partnership }) {
  const updatePlatform = useUpdatePlatformPartnershipMutation();
  const deletePlatform = useDeletePlatformPartnershipMutation();
  const isUpdating = updatePlatform.isPending;
  const isDeleting = deletePlatform.isPending;

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to delete this partnership? This action cannot be undone.')) {
      deletePlatform.mutate(partnership.id);
    }
  };

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    const newActiveState = partnership.active === false ? true : false;
    const payload = { active: newActiveState };
    updatePlatform.mutate({ id: partnership.id, payload });
  };

  return (
    <SharedRowActions
      isActive={partnership.active !== false}
      isUpdating={isUpdating}
      isDeleting={isDeleting}
      onToggleActive={handleToggleActive}
      onDelete={handleDelete}
      entityName="Partnership"
    />
  );
}

const columnHelper = createColumnHelper<Partnership>();

const columns = [

  columnHelper.accessor('name', {
    header: 'Partnership Name',
    cell: (info) => {
      const name = info.getValue();
      if (!name) return (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600">
            <Network className="w-4 h-4" />
          </div>
          <span className="text-slate-400 text-sm">Unnamed Partnership</span>
        </div>
      );
      return (
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600">
            <Network className="w-4 h-4" />
          </div>
          <span className="font-medium text-sm text-slate-700">
            {name}
          </span>
        </div>
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
  columnHelper.accessor('edi_version', {
    header: 'EDI Version',
    cell: (info) => (
      <span className="text-sm text-slate-600 font-medium">
        {info.getValue() || 'N/A'}
      </span>
    ),
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <PartnershipRowActions partnership={info.row.original} />
      </div>
    ),
  }),
];

import type { Partner } from '../context/PartnersContext';

export function PartnershipsTable({ data, availablePartners, isLoading }: { data: Partnership[]; availablePartners: Partner[]; isLoading: boolean }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
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
          <h3 className="text-lg font-bold text-slate-900 mb-2">No Active Partnerships</h3>
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
              <React.Fragment key={row.id}>
                <tr
                  className={`hover:bg-slate-50/50 transition-colors group cursor-pointer ${row.getIsExpanded() ? 'bg-slate-50/50' : ''}`}
                  onClick={() => row.toggleExpanded()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      row.toggleExpanded();
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-expanded={row.getIsExpanded()}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-6 py-4">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
                {row.getIsExpanded() && (
                  <tr>
                    <td colSpan={row.getVisibleCells().length} className="p-0">
                      <PartnershipDetails partnership={row.original} availablePartners={availablePartners} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
