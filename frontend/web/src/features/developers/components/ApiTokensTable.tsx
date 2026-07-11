import React from 'react';
import {
  createColumnHelper,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { DataTable } from '@/components/ui/data-table';
import type { ApiToken } from '../types';
import { useRevokeApiTokenMutation, useDeleteApiTokenMutation } from '../api/apiTokenHooks';
import { Button } from '@/components/ui/button';
import { MoreHorizontal, Trash2, Ban } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { formatDistanceToNow, parseISO } from 'date-fns';

function TokenRowActions({ token }: { token: ApiToken }) {
  const revoke = useRevokeApiTokenMutation();
  const hardDelete = useDeleteApiTokenMutation();

  const handleRevoke = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to revoke this token? Any integrations using it will immediately fail.')) {
      revoke.mutate(token.id);
    }
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to permanently delete this token? This cannot be undone.')) {
      hardDelete.mutate(token.id);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-8 w-8 p-0" onClick={e => e.stopPropagation()}>
          <span className="sr-only">Open menu</span>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Actions</DropdownMenuLabel>
        <DropdownMenuSeparator />

        {token.active && (
          <DropdownMenuItem onClick={handleRevoke} className="text-amber-600 focus:text-amber-600 cursor-pointer">
            <Ban className="mr-2 h-4 w-4" />
            Revoke
          </DropdownMenuItem>
        )}

        <DropdownMenuItem onClick={handleDelete} className="text-red-600 focus:text-red-600 cursor-pointer">
          <Trash2 className="mr-2 h-4 w-4" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const columnHelper = createColumnHelper<ApiToken>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Name',
    cell: (info) => <div className="font-medium text-slate-900">{info.getValue()}</div>,
  }),
  columnHelper.accessor('client_id', {
    header: 'Client ID',
    cell: (info) => <div className="font-mono text-sm text-slate-500">{info.getValue()}</div>,
  }),
  columnHelper.accessor('active', {
    header: 'Status',
    cell: (info) => {
      const active = info.getValue();
      return (
        <Badge variant={active ? 'default' : 'secondary'} className={active ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}>
          {active ? 'Active' : 'Revoked'}
        </Badge>
      );
    },
  }),
  columnHelper.accessor('last_used_at', {
    header: 'Last Used',
    cell: (info) => {
      const val = info.getValue();
      if (!val) return <span className="text-slate-400 italic">Never</span>;
      try {
        return <span className="text-slate-600">{formatDistanceToNow(parseISO(val), { addSuffix: true })}</span>;
      } catch {
        return <span className="text-slate-400 italic">Invalid Date</span>;
      }
    },
  }),
  columnHelper.accessor('created_at', {
    header: 'Created',
    cell: (info) => {
      const val = info.getValue();
      if (val === 'just now') return <span className="text-slate-600">Just now</span>;
      try {
        return <span className="text-slate-600">{formatDistanceToNow(parseISO(val), { addSuffix: true })}</span>;
      } catch {
        return <span className="text-slate-600">{val}</span>;
      }
    },
  }),
  columnHelper.display({
    id: 'actions',
    cell: ({ row }) => <TokenRowActions token={row.original} />,
  }),
];

interface ApiTokensTableProps {
  data: ApiToken[];
  isLoading: boolean;
}

export function ApiTokensTable({ data, isLoading }: ApiTokensTableProps) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return <DataTable table={table} columnsLength={columns.length} dataLength={data.length} isLoading={isLoading} />;
}
