import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Link as LinkIcon, Loader2, Network, Power, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import type { WebhookHookConfig } from '../api/webhookHooks';
import { useDeleteWebhookMutation, useUpdateWebhookMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';
import { WebhookDetails } from './WebhookDetails';

// ─── Delete Confirmation Dialog ────────────────────────────────────────────
interface DeleteWebhookDialogProps {
  config: WebhookHookConfig;
  webhook: Webhook;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function DeleteWebhookDialog({ config, webhook, open, onOpenChange }: DeleteWebhookDialogProps) {
  const [confirmText, setConfirmText] = useState('');
  const deleteMutation = useDeleteWebhookMutation(config);
  const confirmValue = webhook.url;

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(webhook.id);
      setConfirmText('');
      onOpenChange(false);
    } catch {
      // surfaced by mutation
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
          <DialogDescription>This action is permanent and irreversible.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm text-slate-600">
          <p>To confirm, type the exact webhook URL:</p>
          <code className="block bg-slate-100 rounded-lg px-3 py-2 text-xs font-mono break-all text-slate-700">
            {confirmValue}
          </code>
          <Label htmlFor="delete-webhook-confirm-input">Confirmation</Label>
          <Input
            id="delete-webhook-confirm-input"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Paste the webhook URL to confirm"
            className="font-mono text-sm"
            autoComplete="off"
            aria-describedby="delete-webhook-warning"
          />
          <p id="delete-webhook-warning" className="sr-only">
            Warning: This action is permanent and irreversible.
          </p>
        </div>
        {deleteMutation.error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
            {deleteMutation.error.message}
          </div>
        )}
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

// ─── Row Actions ────────────────────────────────────────────────────────────
function WebhookRowActions({ config, webhook }: { config: WebhookHookConfig; webhook: Webhook }) {
  const [showDelete, setShowDelete] = useState(false);
  const updateMutation = useUpdateWebhookMutation(config);
  const isActive = webhook.active;

  const handleToggleActive = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await updateMutation.mutateAsync({ id: webhook.id, payload: { active: !isActive } });
    } catch {
      // surfaced by mutation
    }
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
          disabled={updateMutation.isPending}
          title={
            updateMutation.error
              ? updateMutation.error.message
              : isActive
                ? 'Deactivate Webhook'
                : 'Activate Webhook'
          }
          aria-label={isActive ? 'Deactivate Webhook' : 'Activate Webhook'}
          className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${
            updateMutation.error
              ? 'bg-red-50 border-red-200'
              : isActive
                ? 'bg-emerald-50 border-emerald-200'
                : 'bg-slate-100 border-slate-300'
          } ${updateMutation.isPending ? 'opacity-50 cursor-wait' : ''}`}
        >
          <span
            className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${
              isActive ? 'opacity-100 text-emerald-700' : 'opacity-0'
            }`}
          >
            Active
          </span>
          <span
            className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${
              isActive ? 'opacity-0' : 'opacity-100 text-slate-500'
            }`}
          >
            Inactive
          </span>
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${
              isActive
                ? 'translate-x-[62px] bg-emerald-600 text-white'
                : 'translate-x-0 bg-white text-slate-400'
            }`}
          >
            {updateMutation.isPending ? (
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
          className="p-2 text-red-600 bg-red-50 hover:bg-red-100 rounded-md transition-colors"
          title="Delete Webhook"
          aria-label="Delete Webhook"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <DeleteWebhookDialog
        config={config}
        webhook={webhook}
        open={showDelete}
        onOpenChange={setShowDelete}
      />
    </>
  );
}

// ─── Main Table Component ───────────────────────────────────────────────────

const columnHelper = createColumnHelper<{ webhook: Webhook; config: WebhookHookConfig }>();

const columns = [
  columnHelper.accessor((row) => row.webhook.name, {
    id: 'name',
    header: 'Name',
    cell: (info) => (
      <div className="font-semibold text-slate-900 flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100 shrink-0">
          <Network className="w-4 h-4" />
        </div>
        {info.getValue()}
      </div>
    ),
  }),
  columnHelper.accessor((row) => row.webhook.url, {
    id: 'url',
    header: 'URL',
    cell: (info) => (
      <div className="flex items-center gap-1.5 text-slate-500 font-mono text-xs">
        <LinkIcon className="w-3 h-3 shrink-0" />
        <span className="truncate max-w-xs" title={info.getValue()}>
          {info.getValue()}
        </span>
      </div>
    ),
  }),
  columnHelper.accessor((row) => row.webhook.active, {
    id: 'status',
    header: 'Status',
    cell: (info) => {
      return (
        <span
          className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ${
            info.row.original.webhook.active
              ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
              : 'bg-slate-50 text-slate-600 ring-slate-500/10'
          }`}
        >
          {info.row.original.webhook.active ? 'Active' : 'Inactive'}
        </span>
      );
    },
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <WebhookRowActions config={info.row.original.config} webhook={info.row.original.webhook} />
      </div>
    ),
  }),
];

interface WebhooksTableProps {
  config: WebhookHookConfig;
  data: Webhook[];
  isLoading: boolean;
}

export function WebhooksTable({ config, data, isLoading }: WebhooksTableProps) {
  // We map the data so each row has access to the config (needed for actions/mutations)
  const tableData = React.useMemo(
    () => data.map((webhook) => ({ webhook, config })),
    [data, config],
  );

  const table = useReactTable({
    data: tableData,
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
      emptyTitle="No webhooks configured"
      columnsLength={columns.length}
      renderExpandedRow={(row) => (
        <WebhookDetails
          config={config}
          webhook={row.original.webhook}
          onCancel={() => row.toggleExpanded()}
        />
      )}
    />
  );
}
