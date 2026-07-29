import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Network, ShieldCheck } from 'lucide-react';
import React from 'react';
import {
  useDeleteAS2PartnershipMutation,
  useUpdateAS2PartnershipMutation,
} from '../api/partnerHooks';
import type { Partnership } from '../context/AS2PartnersContext';
import { PartnershipDetails } from './PartnershipDetails';
import { SharedRowActions } from './SharedRowActions';

function PartnershipRowActions({ partnership }: { partnership: Partnership }) {
  const updatePlatform = useUpdateAS2PartnershipMutation();
  const deletePlatform = useDeleteAS2PartnershipMutation();
  const isUpdating = updatePlatform.isPending;
  const isDeleting = deletePlatform.isPending;

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (
      confirm('Are you sure you want to delete this partnership? This action cannot be undone.')
    ) {
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

import type { Partner } from '../context/AS2PartnersContext';

export function PartnershipsTable({
  data,
  availablePartners,
  isLoading,
}: {
  data: Partnership[];
  availablePartners: Partner[];
  isLoading: boolean;
}) {
  const columns = React.useMemo(() => {
    const getPartnerName = (id: string) => {
      const p = availablePartners.find((ap) => ap.id === id);
      if (!p) return id.split('-')[0] + '...';
      if (p.name) return p.name;
      if ('as2_id' in p) return p.as2_id;
      return id.split('-')[0] + '...';
    };

    return [
      columnHelper.accessor('name', {
        header: 'Partnership Name',
        cell: (info) => {
          const name = info.getValue();
          if (!name)
            return (
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
              <span className="font-medium text-sm text-slate-700">{name}</span>
            </div>
          );
        },
      }),

      columnHelper.accessor('local_partner_id', {
        header: 'Local Partner',
        cell: (info) => {
          const resolvedName = getPartnerName(info.getValue());
          return (
            <span
              className="text-sm font-medium text-slate-700 truncate max-w-[120px]"
              title={resolvedName}
            >
              {resolvedName}
            </span>
          );
        },
      }),
      columnHelper.accessor('remote_partner_id', {
        header: 'Remote Partner',
        cell: (info) => {
          const resolvedName = getPartnerName(info.getValue());
          return (
            <span
              className="text-sm font-medium text-slate-700 truncate max-w-[120px]"
              title={resolvedName}
            >
              {resolvedName}
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
        header: '',
        cell: (info) => (
          <div className="flex justify-end">
            <PartnershipRowActions partnership={info.row.original} />
          </div>
        ),
      }),
    ];
  }, [availablePartners]);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      dataLength={data.length}
      emptyIcon={<Network className="w-8 h-8" />}
      emptyTitle="No Active Partnerships"
      columnsLength={columns.length}
      renderExpandedRow={(row) => (
        <PartnershipDetails
          partnership={row.original}
          availablePartners={availablePartners}
          onCancel={() => row.toggleExpanded()}
        />
      )}
    />
  );
}
