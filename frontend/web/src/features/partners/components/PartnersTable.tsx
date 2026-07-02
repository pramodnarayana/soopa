import React from 'react';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  getExpandedRowModel,
} from '@tanstack/react-table';
import type { Partner } from '../context/PartnersContext';
import { useDeletePlatformPartner, useDeleteSftpPartner, useUpdatePlatformPartnerMutation, useUpdateSftpPartnerMutation } from '../api/partnerHooks';
import { Server, CheckCircle2 } from 'lucide-react';
import { PartnerDetails } from './PartnerDetails';
import { SharedRowActions } from './SharedRowActions';
import { useToast } from '@/hooks/use-toast';

function PartnerRowActions({ partner, scope }: { partner: Partner; scope: 'platform' | 'tenant' }) {
  const { toast } = useToast();
  const deletePlatform = useDeletePlatformPartner();
  const deleteSftp = useDeleteSftpPartner();
  const updatePlatform = useUpdatePlatformPartnerMutation();
  const updateSftp = useUpdateSftpPartnerMutation();

  const isDeleting = deletePlatform.isPending || deleteSftp.isPending;
  const isUpdating = updatePlatform.isPending || updateSftp.isPending;

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation(); // prevent row expansion
    if (!window.confirm(`Are you sure you want to delete ${partner.name}?`)) return;

    if (scope === 'platform') {
      deletePlatform.mutate(partner.id, {
        onSuccess: () => toast({ title: 'Success', description: 'Partner deleted successfully.' })
      });
    } else {
      deleteSftp.mutate(partner.id, {
        onSuccess: () => toast({ title: 'Success', description: 'Partner deleted successfully.' })
      });
    }
  };

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    const newActiveState = partner.active === false ? true : false;
    const payload = { active: newActiveState };

    if (scope === 'platform') {
      updatePlatform.mutate({ id: partner.id, payload }, {
        onSuccess: () => toast({ title: 'Success', description: `Partner ${newActiveState ? 'activated' : 'deactivated'}.` })
      });
    } else {
      updateSftp.mutate({ id: partner.id, payload }, {
        onSuccess: () => toast({ title: 'Success', description: `Partner ${newActiveState ? 'activated' : 'deactivated'}.` })
      });
    }
  };

  return (
    <SharedRowActions
      isActive={partner.active !== false}
      isUpdating={isUpdating}
      isDeleting={isDeleting}
      onToggleActive={handleToggleActive}
      onDelete={handleDelete}
      entityName="Partner"
    />
  );
}

const columnHelper = createColumnHelper<Partner>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Partner Name',
    cell: (info) => (
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
          <Server className="w-4 h-4" />
        </div>
        <span className="font-semibold text-slate-900">{info.getValue()}</span>
      </div>
    ),
  }),
  columnHelper.accessor('as2_id', {
    header: 'AS2 ID',
    cell: (info) => (
      <span className="font-mono text-sm px-2 py-1 bg-slate-100 rounded-md text-slate-600 border border-slate-200">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('type', {
    header: 'Type',
    cell: (info) => (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
        <CheckCircle2 className="w-3.5 h-3.5" />
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('is_local', {
    header: 'Role',
    cell: (info) => {
      const isLocal = info.getValue();
      if (isLocal === undefined) return null;
      return (
        <span className="text-sm font-medium text-slate-500">
          {isLocal ? 'Local Station' : 'Remote Station'}
        </span>
      );
    },
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <PartnerRowActions partner={info.row.original} scope={(info.table.options.meta as any)?.scope || 'tenant'} />
      </div>
    ),
  }),
];

export function PartnersTable({ data, isLoading, scope = 'tenant' }: { data: Partner[]; isLoading: boolean; scope?: 'platform' | 'tenant' }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
    meta: {
      scope
    }
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
            <Server className="w-8 h-8" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">No Active Trading Partners</h3>
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
                      <PartnerDetails partner={row.original} scope={scope} />
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
