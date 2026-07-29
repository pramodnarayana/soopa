import { Button } from '@soopa/ui/components/ui/button';
import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@soopa/ui/components/ui/dialog';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { createColumnHelper, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { Key, Loader2, Pencil, Power, Trash2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Badge } from '../../../components/ui/badge';
import { useDeleteApiTokenMutation, useUpdateApiTokenMutation } from '../api/apiTokenHooks';
import type { ApiToken } from '../types';

// ---------------------------------------------------------------------------
// Delete confirmation dialog
// ---------------------------------------------------------------------------
function DeleteTokenDialog({
  token,
  open,
  onOpenChange,
}: {
  token: ApiToken;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [confirmText, setConfirmText] = useState('');
  const deleteMutation = useDeleteApiTokenMutation();

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(token.id);
      setConfirmText('');
      onOpenChange(false);
    } catch {
      // Rejection handled by mutation's onError or toast system
    }
  };

  const handleClose = () => {
    setConfirmText('');
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-red-600">Delete API Token</DialogTitle>
          <DialogDescription render={<div className="space-y-3 text-sm text-slate-600" />}>
            <p>
              This action is{' '}
              <span className="font-semibold text-slate-900">permanent and irreversible</span>. Any
              integrations authenticating with this token will immediately fail.
            </p>
            <p>To confirm, type the token name below:</p>
            <code className="block bg-slate-100 rounded-lg px-3 py-2 text-xs font-mono break-all text-slate-700">
              {token.name}
            </code>
            <Input
              id={`delete-token-confirm-${token.id}`}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type the token name to confirm"
              className="font-mono text-sm"
              autoComplete="off"
            />
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            id={`delete-token-confirm-btn-${token.id}`}
            variant="destructive"
            disabled={confirmText !== token.name || deleteMutation.isPending}
            onClick={handleDelete}
          >
            {deleteMutation.isPending ? 'Deleting…' : 'Delete Permanently'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Rename dialog
// ---------------------------------------------------------------------------
function RenameTokenDialog({
  token,
  open,
  onOpenChange,
}: {
  token: ApiToken;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState(token.name);

  useEffect(() => {
    if (open) {
      setName(token.name);
    }
  }, [open, token.name]);

  const updateMutation = useUpdateApiTokenMutation();

  const handleRename = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === token.name) {
      onOpenChange(false);
      return;
    }
    try {
      await updateMutation.mutateAsync({ id: token.id, data: { name: trimmed } });
      onOpenChange(false);
    } catch {
      // Rejection handled by mutation's onError or toast system
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename API Token</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleRename} className="space-y-4">
          <div className="grid gap-2">
            <Label htmlFor={`rename-token-${token.id}`}>Token Name</Label>
            <Input
              id={`rename-token-${token.id}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. ERP Integration Prod"
              required
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMutation.isPending || !name.trim()}>
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------
function TokenRowActions({ token }: { token: ApiToken }) {
  const [showDelete, setShowDelete] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const updateMutation = useUpdateApiTokenMutation();
  const isActive = token.active;
  const isUpdating = updateMutation.isPending;
  const isDeleting = false; // The actual delete mutation is managed in the modal
  const entityName = 'API Token';

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    updateMutation.mutate({ id: token.id, data: { active: !isActive } });
  };

  return (
    <>
      <div
        className="flex items-center gap-4 pr-4"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          role="switch"
          aria-checked={isActive}
          onClick={handleToggleActive}
          disabled={isUpdating}
          title={isActive ? `Deactivate ${entityName}` : `Activate ${entityName}`}
          aria-label={isActive ? `Deactivate ${entityName}` : `Activate ${entityName}`}
          className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${isActive ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-100 border-slate-300'} ${isUpdating ? 'opacity-50 cursor-wait' : ''}`}
        >
          <span
            className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-100 text-emerald-700' : 'opacity-0'}`}
          >
            Active
          </span>
          <span
            className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-0' : 'opacity-100 text-slate-500'}`}
          >
            Inactive
          </span>
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${isActive ? 'translate-x-[62px] bg-emerald-600 text-white' : 'translate-x-0 bg-white text-slate-400'}`}
          >
            {isUpdating ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Power className="w-3 h-3" />
            )}
          </span>
        </button>

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowRename(true);
          }}
          className="p-2 text-slate-600 bg-slate-50 hover:bg-slate-200 rounded-md transition-colors"
          title={`Rename ${entityName}`}
          aria-label={`Rename ${entityName}`}
        >
          <Pencil className="w-4 h-4" />
        </button>

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowDelete(true);
          }}
          disabled={isDeleting}
          className="p-2 text-red-600 bg-red-50 hover:bg-red-100 rounded-md transition-colors"
          title={`Delete ${entityName}`}
          aria-label={`Delete ${entityName}`}
        >
          {isDeleting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Trash2 className="w-4 h-4" />
          )}
        </button>
      </div>

      <RenameTokenDialog token={token} open={showRename} onOpenChange={setShowRename} />
      <DeleteTokenDialog token={token} open={showDelete} onOpenChange={setShowDelete} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Table columns
// ---------------------------------------------------------------------------
const columnHelper = createColumnHelper<ApiToken>();

const columns = [
  columnHelper.accessor('name', {
    header: 'Name',
    cell: (info) => (
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-violet-50 flex items-center justify-center text-violet-600 border border-violet-100">
          <Key className="w-4 h-4" />
        </div>
        <span className="font-semibold text-slate-900">{info.getValue()}</span>
      </div>
    ),
  }),
  columnHelper.accessor('client_id', {
    header: 'Client ID',
    cell: (info) => (
      <div className="font-mono text-sm text-slate-500 truncate max-w-[200px]">
        {info.getValue()}
      </div>
    ),
  }),
  columnHelper.accessor('active', {
    header: 'Status',
    cell: (info) => {
      const active = info.getValue();
      return (
        <Badge
          variant={active ? 'default' : 'secondary'}
          className={
            active
              ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
              : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
          }
        >
          <span
            className={`w-1.5 h-1.5 rounded-full mr-1.5 inline-block ${
              active ? 'bg-emerald-500' : 'bg-slate-400'
            }`}
          />
          {active ? 'Active' : 'Inactive'}
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
        return (
          <span className="text-slate-600">
            {formatDistanceToNow(parseISO(val), { addSuffix: true })}
          </span>
        );
      } catch {
        return <span className="text-slate-400 italic">Invalid date</span>;
      }
    },
  }),
  columnHelper.accessor('created_at', {
    header: 'Created',
    cell: (info) => {
      const val = info.getValue();
      if (val === 'just now') return <span className="text-slate-600">Just now</span>;
      try {
        return (
          <span className="text-slate-600">
            {formatDistanceToNow(parseISO(val), { addSuffix: true })}
          </span>
        );
      } catch {
        return <span className="text-slate-600">{val}</span>;
      }
    },
  }),
  columnHelper.display({
    id: 'actions',
    cell: ({ row }) => (
      <div className="flex justify-end">
        <TokenRowActions token={row.original} />
      </div>
    ),
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

  return (
    <DataTable
      table={table}
      columnsLength={columns.length}
      dataLength={data.length}
      isLoading={isLoading}
      emptyIcon={<Key className="w-8 h-8" />}
      emptyTitle="No API Tokens"
    />
  );
}
