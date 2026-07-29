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
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Link, Loader2, Network, Power, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { Badge } from '../../../components/ui/badge';
import { useDeleteWebhookMutation, useUpdateWebhookStatusMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';
import { WebhookDetails } from './WebhookDetails';

// ---------------------------------------------------------------------------
// Delete confirmation dialog (requires typing the exact webhook URL)
// ---------------------------------------------------------------------------
function DeleteWebhookDialog({
  webhook,
  open,
  onOpenChange,
}: {
  webhook: Webhook;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [confirmText, setConfirmText] = useState('');
  const deleteMutation = useDeleteWebhookMutation();
  const confirmValue = webhook.url ?? webhook.id;

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(webhook.id);
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
          <DialogTitle className="text-red-600">Delete Webhook</DialogTitle>
          <DialogDescription render={<div className="space-y-3 text-sm text-slate-600" />}>
            <p>
              This action is{' '}
              <span className="font-semibold text-slate-900">permanent and irreversible</span>. Any
              live integrations pointing to this webhook will immediately stop receiving data.
            </p>
            <p>To confirm, type the exact webhook URL below:</p>
            <code className="block bg-slate-100 rounded-lg px-3 py-2 text-xs font-mono break-all text-slate-700">
              {confirmValue}
            </code>
            <Input
              id="delete-webhook-confirm-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Paste the webhook URL to confirm"
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
            id="delete-webhook-confirm-btn"
            variant="destructive"
            disabled={confirmText !== confirmValue || deleteMutation.isPending}
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
// Row actions
// ---------------------------------------------------------------------------
function WebhookRowActions({ webhook }: { webhook: Webhook }) {
  const [showDelete, setShowDelete] = useState(false);
  const toggleStatus = useUpdateWebhookStatusMutation();
  const isActive = webhook.status === 'ACTIVE';
  const isUpdating = toggleStatus.isPending;
  const isDeleting = false; // Actual delete state is in the modal
  const entityName = 'Webhook';

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    toggleStatus.mutate({ id: webhook.id, active: !isActive });
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

      <DeleteWebhookDialog webhook={webhook} open={showDelete} onOpenChange={setShowDelete} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Table columns
// ---------------------------------------------------------------------------
const columnHelper = createColumnHelper<Webhook>();

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
  columnHelper.accessor('url', {
    header: 'URL',
    cell: (info) => {
      const url = info.getValue();
      if (!url) return <span className="text-slate-400 italic">Not set</span>;
      return (
        <div className="flex items-center gap-2">
          <Link className="w-3 h-3 text-slate-400" />
          <span className="font-mono text-sm text-slate-600 truncate max-w-[250px]">{url}</span>
        </div>
      );
    },
  }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => {
      const active = info.getValue() === 'ACTIVE';
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
  columnHelper.display({
    id: 'actions',
    cell: ({ row }) => (
      <div className="flex justify-end">
        <WebhookRowActions webhook={row.original} />
      </div>
    ),
  }),
];

interface WebhooksTableProps {
  data: Webhook[];
  isLoading: boolean;
}

export function WebhooksTable({ data, isLoading }: WebhooksTableProps) {
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
      emptyTitle="No Webhooks"
      columnsLength={columns.length}
      renderExpandedRow={(row) => (
        <WebhookDetails webhook={row.original} onCancel={() => row.toggleExpanded(false)} />
      )}
    />
  );
}
