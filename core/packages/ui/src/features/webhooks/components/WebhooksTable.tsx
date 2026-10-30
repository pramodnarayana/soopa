import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Link as LinkIcon, Network, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
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
import { type FieldDef, QueryBuilder, useClientFilter } from '../../../components/ui/query-builder';
import { Switch } from '../../../components/ui/switch';
import type { WebhookHookConfig } from '../api/webhookHooks';
import { useDeleteWebhookMutation, useUpdateWebhookMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';
import { WebhookDetails } from './WebhookDetails';

// ─── Delete Confirmation Dialog ────────────────────────────────────────────
interface DeleteWebhookDialogProps {
  readonly config: WebhookHookConfig;
  readonly webhook: Webhook;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

function DeleteWebhookDialog({ config, webhook, open, onOpenChange }: DeleteWebhookDialogProps) {
  const [confirmText, setConfirmText] = useState('');
  const [problemMessage, setProblemMessage] = useState<string | null>(null);
  const deleteMutation = useDeleteWebhookMutation(config);
  const confirmValue = webhook.url;

  const handleClose = (): void => {
    setConfirmText('');
    setProblemMessage(null);
    onOpenChange(false);
  };

  const handleDelete = async (): Promise<void> => {
    setProblemMessage(null);
    const result = await deleteMutation.mutateAsync(webhook.id);
    if (!result.ok) {
      setProblemMessage(result.error.message);
      return;
    }
    handleClose();
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
          <code className="block rounded-lg bg-slate-100 px-3 py-2 font-mono text-xs break-all text-slate-700">
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
        {problemMessage && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
            {problemMessage}
          </div>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            id="delete-webhook-confirm-btn"
            type="button"
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
function WebhookRowActions({
  config,
  webhook,
}: {
  readonly config: WebhookHookConfig;
  readonly webhook: Webhook;
}) {
  const [showDelete, setShowDelete] = useState(false);
  const updateMutation = useUpdateWebhookMutation(config);
  const isActive = webhook.active;

  const handleToggleActive = async (nextChecked: boolean): Promise<void> => {
    const result = await updateMutation.mutateAsync({
      id: webhook.id,
      payload: { active: nextChecked },
    });
    if (!result.ok) {
      toast.error(result.error.message || 'Failed to update webhook status');
    }
  };

  return (
    <>
      <div
        className="flex items-center gap-4 pr-4"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <Switch
            checked={isActive}
            onCheckedChange={(checked) => {
              void handleToggleActive(checked);
            }}
            disabled={updateMutation.isPending}
            aria-label={isActive ? 'Deactivate Webhook' : 'Activate Webhook'}
          />
          <span className="w-14 text-xs font-medium text-slate-600">
            {isActive ? 'Active' : 'Inactive'}
          </span>
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={(e) => {
            e.stopPropagation();
            setShowDelete(true);
          }}
          className="bg-red-50 text-red-600 hover:bg-red-100 hover:text-red-700"
          title="Delete Webhook"
          aria-label="Delete Webhook"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
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
      <div className="flex items-center gap-2 font-semibold text-slate-900">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-indigo-100 bg-indigo-50 text-indigo-600">
          <Network className="h-4 w-4" />
        </div>
        {info.getValue()}
      </div>
    ),
  }),
  columnHelper.accessor((row) => row.webhook.url, {
    id: 'url',
    header: 'URL',
    cell: (info) => (
      <div className="flex items-center gap-1.5 font-mono text-xs text-slate-500">
        <LinkIcon className="h-3 w-3 shrink-0" />
        <span className="max-w-xs truncate" title={info.getValue()}>
          {info.getValue()}
        </span>
      </div>
    ),
  }),
  columnHelper.accessor((row) => row.webhook.active, {
    id: 'status',
    header: 'Status',
    cell: (info) => (
      <span
        className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ${
          info.row.original.webhook.active
            ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
            : 'bg-slate-50 text-slate-600 ring-slate-500/10'
        }`}
      >
        {info.row.original.webhook.active ? 'Active' : 'Inactive'}
      </span>
    ),
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

const availableFields: FieldDef[] = [
  { id: 'webhook.name', label: 'Name', type: 'text' },
  { id: 'webhook.url', label: 'URL', type: 'text' },
  {
    id: 'webhook.active',
    label: 'Status',
    type: 'boolean',
    operators: ['eq'],
  },
];

interface WebhooksTableProps {
  readonly config: WebhookHookConfig;
  readonly data: Webhook[];
  readonly isLoading: boolean;
}

export function WebhooksTable({ config, data, isLoading }: WebhooksTableProps) {
  const rawTableData = React.useMemo(
    () => data.map((webhook) => ({ webhook, config })),
    [data, config],
  );

  const { filters, setFilters, filteredData: tableData } = useClientFilter(rawTableData);

  const table = useReactTable({
    data: tableData,
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
        dataLength={tableData.length}
        emptyIcon={<Network className="h-8 w-8" />}
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
    </div>
  );
}
