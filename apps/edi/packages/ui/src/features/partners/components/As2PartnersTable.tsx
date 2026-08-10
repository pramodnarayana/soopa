import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  type FieldDef,
  QueryBuilder,
  useClientFilter,
} from '@soopa/ui/components/ui/query-builder';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { CheckCircle2, Server } from 'lucide-react';
import React from 'react';
import { useDeleteAS2PartnerMutation, useUpdateAS2PartnerMutation } from '../api/partnerHooks';
import type { AS2Partner } from '../types';
import { As2PartnerDetails } from './As2PartnerDetails';
import { SharedRowActions } from './SharedRowActions';

function As2PartnerRowActions({ partner }: { partner: AS2Partner }) {
  const deletePlatform = useDeleteAS2PartnerMutation();
  const updatePlatform = useUpdateAS2PartnerMutation();

  const isDeleting = deletePlatform.isPending;
  const isUpdating = updatePlatform.isPending;

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation(); // prevent row expansion
    if (!window.confirm(`Are you sure you want to delete ${partner.name}?`)) return;
    deletePlatform.mutate(partner.id);
  };

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    const newActiveState = partner.active === false ? true : false;
    updatePlatform.mutate({ id: partner.id, payload: { active: newActiveState } });
  };

  return (
    <SharedRowActions
      isActive={partner.active !== false}
      isUpdating={isUpdating}
      isDeleting={isDeleting}
      onToggleActive={handleToggleActive}
      onDelete={handleDelete}
      entityName="AS2 Partner"
    />
  );
}

const columnHelper = createColumnHelper<AS2Partner>();

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
        <As2PartnerRowActions partner={info.row.original} />
      </div>
    ),
  }),
];

const availableFields: FieldDef[] = [
  { id: 'name', label: 'Partner Name', type: 'text' },
  { id: 'as2_id', label: 'AS2 ID', type: 'text' },
  { id: 'type', label: 'Type', type: 'text' },
  {
    id: 'is_local',
    label: 'Role',
    type: 'enum',
    operators: ['eq'],
    options: [
      { label: 'Local Station', value: 'true' },
      { label: 'Remote Station', value: 'false' },
    ],
  },
];

export function As2PartnersTable({
  data: rawData,
  isLoading,
}: {
  data: AS2Partner[];
  isLoading: boolean;
}) {
  const { filters, setFilters, filteredData: data } = useClientFilter(rawData);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
  });

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <QueryBuilder fields={availableFields} rules={filters} onChange={setFilters} />
      </div>
      <DataTable
        table={table}
        isLoading={isLoading}
        dataLength={data.length}
        emptyIcon={<Server className="w-8 h-8" />}
        emptyTitle="No Active AS2 Trading Partners"
        columnsLength={columns.length}
        renderExpandedRow={(row) => (
          <As2PartnerDetails partner={row.original} onCancel={() => row.toggleExpanded()} />
        )}
      />
    </div>
  );
}
