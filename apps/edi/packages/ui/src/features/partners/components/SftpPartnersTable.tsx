import { DataTable } from '@/components/ui/data-table';
import React from 'react';
import {
  createColumnHelper,

  getCoreRowModel,
  useReactTable,
  getExpandedRowModel,
} from '@tanstack/react-table';

import type { SFTPPartner } from '../types';
import { useDeleteSftpPartner, useUpdateSftpPartnerMutation } from '../api/partnerHooks';
import { Server, HardDrive } from 'lucide-react';
import { SftpPartnerDetails } from './SftpPartnerDetails';
import { SharedRowActions } from './SharedRowActions';

function SftpPartnerRowActions({ partner }: { partner: SFTPPartner }) {
  const deleteSftp = useDeleteSftpPartner();
  const updateSftp = useUpdateSftpPartnerMutation();

  const isDeleting = deleteSftp.isPending;
  const isUpdating = updateSftp.isPending;

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to delete ${partner.name}?`)) return;
    deleteSftp.mutate(partner.id);
  };

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    const newActiveState = partner.active === false ? true : false;
    updateSftp.mutate({ id: partner.id, payload: { active: newActiveState } });
  };

  return (
    <SharedRowActions
      isActive={partner.active !== false}
      isUpdating={isUpdating}
      isDeleting={isDeleting}
      onToggleActive={handleToggleActive}
      onDelete={handleDelete}
      entityName="SFTP Partner"
    />
  );
}

const columnHelper = createColumnHelper<SFTPPartner>();

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
  columnHelper.accessor('host', {
    header: 'Host',
    cell: (info) => {
      const host = info.getValue();
      if (!host) return null;
      return (
        <span className="font-mono text-sm px-2 py-1 bg-slate-100 rounded-md text-slate-600 border border-slate-200">
          {host}
        </span>
      );
    },
  }),
  columnHelper.accessor('username', {
    header: 'Username',
    cell: (info) => {
      const username = info.getValue();
      if (!username) return null;
      return (
        <span className="text-sm font-medium text-slate-500">
          {username}
        </span>
      );
    },
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <SftpPartnerRowActions partner={info.row.original} />
      </div>
    ),
  }),
];

export function SftpPartnersTable({ data, isLoading }: { data: SFTPPartner[]; isLoading: boolean }) {

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
      emptyIcon={<HardDrive className="w-8 h-8" />}
      emptyTitle="No Active SFTP Partners"
      columnsLength={columns.length}
      renderExpandedRow={(row) => <SftpPartnerDetails partner={row.original} onCancel={() => row.toggleExpanded()} />}
    />
  );
}
