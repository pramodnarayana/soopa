import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { AlertTriangle, Check, Copy, Key, Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useClipboardCopy } from '../../components/observability/use-clipboard-copy';
import { Button } from '../../components/ui/button';
import { DataTable } from '../../components/ui/data-table';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Switch } from '../../components/ui/switch';
import type { ApiTokenHookConfig } from './api/apiTokenHooks';
import {
  useApiTokensQuery,
  useCreateApiTokenMutation,
  useDeleteApiTokenMutation,
  useUpdateApiTokenMutation,
} from './api/apiTokenHooks';
import type { ApiToken, ApiTokenCreated } from './types';

function CopyFieldRow({ label, value }: { readonly label: string; readonly value: string }) {
  const { copied, copyText } = useClipboardCopy(2_000);

  return (
    <div className="grid gap-1.5">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      <div className="flex gap-2">
        <Input value={value} readOnly type="text" variant="code" />
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => {
            void copyText(value);
          }}
          aria-label={`Copy ${label}`}
        >
          {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}

// ─── Token Credentials Modal ────────────────────────────────────────────────
function TokenCredentialsModal({
  token,
  onClose,
}: {
  readonly token: ApiTokenCreated;
  readonly onClose: () => void;
}) {
  const secretSegment = token.token.split('.')[1] ?? '';

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-xl">Token Generated Successfully</DialogTitle>
          <DialogDescription>
            Copy your client secret now. It will never be shown again.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <div>
            <p className="font-semibold text-amber-800">Store this secret securely</p>
            <p className="text-amber-700">
              If you lose this secret, you must generate a new token. We never store the raw secret.
            </p>
          </div>
        </div>

        <div className="grid gap-4 py-2">
          <CopyFieldRow label="Client ID" value={token.client_id} />
          <CopyFieldRow label="Client Secret" value={secretSegment} />
          <CopyFieldRow label="Combined Token (Bearer Token)" value={token.token} />
        </div>

        <div className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900">
          <p className="mb-1 font-semibold text-indigo-950">Developer Note: How to authenticate</p>
          <p className="text-indigo-800">
            Include the Combined Token in your HTTP requests using the standard Authorization
            header. If using Postman, select <strong>"Bearer Token"</strong> and paste the Combined
            Token exactly as is.
          </p>
          <code className="mt-2 block rounded border border-indigo-100 bg-white p-2.5 font-mono text-xs text-indigo-950">
            Authorization: Bearer {'<COMBINED_TOKEN>'}
          </code>
          <p className="mt-2 text-xs font-medium text-indigo-700">
            Note: Do not manually type the word "Bearer" when using Postman's Auth tab, as Postman
            adds it automatically.
          </p>
        </div>

        <DialogFooter>
          <Button type="button" onClick={onClose}>
            I've saved the credentials
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Create Token Dialog ─────────────────────────────────────────────────────
function CreateApiTokenDialog({
  config,
  onCreated,
}: {
  readonly config: ApiTokenHookConfig;
  readonly onCreated: (token: ApiTokenCreated) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const createMutation = useCreateApiTokenMutation(config);

  const handleCreate = async (): Promise<void> => {
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    const result = await createMutation.mutateAsync({ name: trimmed });
    if (!result.ok) {
      toast.error(result.error.message || 'Failed to generate API token. Please try again.');
      return;
    }
    setOpen(false);
    setName('');
    onCreated(result.value);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button id="generate-api-token-btn" type="button" size="cta" onClick={() => setOpen(true)}>
        <Plus className="mr-1 h-4 w-4" />
        Generate Token
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Key className="h-5 w-5 text-indigo-600" />
            Generate New API Token
          </DialogTitle>
          <DialogDescription>
            Create a new token for machine-to-machine integrations.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <Label htmlFor="create-token-name">Token Name</Label>
          <Input id="create-token-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            size="sm"
            onClick={handleCreate}
            disabled={!name.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? 'Generating…' : 'Generate Token'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Delete Token Dialog ─────────────────────────────────────────────────────
function DeleteTokenDialog({
  config,
  token,
  open,
  onOpenChange,
}: {
  readonly config: ApiTokenHookConfig;
  readonly token: ApiToken;
  readonly open: boolean;
  readonly onOpenChange: (v: boolean) => void;
}) {
  const [confirmText, setConfirmText] = useState('');
  const deleteMutation = useDeleteApiTokenMutation(config);

  const handleDelete = async (): Promise<void> => {
    const result = await deleteMutation.mutateAsync(token.id);
    if (!result.ok) {
      toast.error(result.error.message || 'Failed to delete API token. Please try again.');
      return;
    }
    setConfirmText('');
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setConfirmText('');
        onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-red-600">Delete API Token</DialogTitle>
          <DialogDescription>
            This action is permanent and irreversible. Any integrations using this token will
            immediately fail.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm text-slate-600">
          <p>To confirm, type the token name:</p>
          <code className="block rounded-lg bg-slate-100 px-3 py-2 font-mono text-xs break-all text-slate-700">
            {token.name}
          </code>
          <Label htmlFor={`delete-token-confirm-${token.id}`}>Confirmation</Label>
          <Input
            id={`delete-token-confirm-${token.id}`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            variant="code"
            autoComplete="off"
            aria-describedby={`delete-token-warning-${token.id}`}
          />
          <p id={`delete-token-warning-${token.id}`} className="sr-only">
            Warning: This action is permanent and irreversible. Any integrations using this token
            will immediately fail.
          </p>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            id={`delete-token-confirm-btn-${token.id}`}
            type="button"
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

// ─── Rename Token Dialog ─────────────────────────────────────────────────────
function RenameTokenDialog({
  config,
  token,
  open,
  onOpenChange,
}: {
  readonly config: ApiTokenHookConfig;
  readonly token: ApiToken;
  readonly open: boolean;
  readonly onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState(token.name);
  const updateMutation = useUpdateApiTokenMutation(config);

  useEffect(() => {
    if (open) {
      setName(token.name);
    }
  }, [open, token.name]);

  const handleRename = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === token.name) {
      onOpenChange(false);
      return;
    }
    const result = await updateMutation.mutateAsync({ id: token.id, data: { name: trimmed } });
    if (!result.ok) {
      toast.error(result.error.message || 'Failed to rename API token. Please try again.');
      return;
    }
    onOpenChange(false);
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

// ─── Token Row Actions ───────────────────────────────────────────────────────
function TokenRowActions({
  config,
  token,
}: {
  readonly config: ApiTokenHookConfig;
  readonly token: ApiToken;
}) {
  const [showDelete, setShowDelete] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const updateMutation = useUpdateApiTokenMutation(config);
  const isActive = token.active;

  const handleToggleActive = (nextChecked: boolean): void => {
    updateMutation.mutate(
      { id: token.id, data: { active: nextChecked } },
      {
        onSuccess: (result) => {
          if (!result.ok) {
            toast.error(result.error.message || 'Failed to toggle token status. Please try again.');
          }
        },
      },
    );
  };

  return (
    <>
      <div
        className="flex items-center gap-3 pr-4"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <Switch
            checked={isActive}
            onCheckedChange={handleToggleActive}
            disabled={updateMutation.isPending}
            aria-label={isActive ? 'Deactivate token' : 'Activate token'}
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
            setShowRename(true);
          }}
          className="text-slate-500 hover:bg-indigo-50 hover:text-indigo-600"
          title="Rename token"
          aria-label="Rename token"
        >
          <Pencil className="h-4 w-4" />
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={(e) => {
            e.stopPropagation();
            setShowDelete(true);
          }}
          className="bg-red-50 text-red-600 hover:bg-red-100 hover:text-red-700"
          title="Delete token"
          aria-label="Delete token"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <DeleteTokenDialog
        config={config}
        token={token}
        open={showDelete}
        onOpenChange={setShowDelete}
      />
      <RenameTokenDialog
        config={config}
        token={token}
        open={showRename}
        onOpenChange={setShowRename}
      />
    </>
  );
}

// ─── Token Details ────────────────────────────────────────────────────────────
function TokenDetails({
  token,
  config,
}: {
  readonly token: ApiToken;
  readonly config: ApiTokenHookConfig;
}) {
  const [name, setName] = useState(token.name);
  const updateMutation = useUpdateApiTokenMutation(config);

  const handleSave = async (): Promise<void> => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === token.name) {
      return;
    }
    const result = await updateMutation.mutateAsync({ id: token.id, data: { name: trimmed } });
    if (!result.ok) {
      toast.error(result.error.message || 'Failed to update API token. Please try again.');
    }
  };

  return (
    <div className="grid gap-8 border-b border-slate-100 bg-slate-50/50 p-4 text-sm text-slate-600 md:grid-cols-2">
      <div className="grid gap-3">
        <div className="space-y-1">
          <Label htmlFor={`token-name-${token.id}`}>Token Name</Label>
          <div className="flex max-w-sm gap-2">
            <Input
              id={`token-name-${token.id}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button
              type="button"
              size="sm"
              onClick={handleSave}
              disabled={updateMutation.isPending || name.trim() === token.name || !name.trim()}
            >
              {updateMutation.isPending ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Check className="mr-1 h-3 w-3" />
              )}
              Save
            </Button>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 content-start gap-4 pt-1">
        <div>
          <div className="mb-1 font-semibold text-slate-900">Client ID</div>
          <div className="font-mono text-xs break-all text-slate-500">{token.client_id}</div>
        </div>
        <div>
          <div className="mb-1 font-semibold text-slate-900">Status</div>
          <div>{token.active ? 'Active' : 'Inactive'}</div>
        </div>
      </div>
    </div>
  );
}

// ─── Table Columns ────────────────────────────────────────────────────────────
const columnHelper = createColumnHelper<{ token: ApiToken; config: ApiTokenHookConfig }>();

const columns = [
  columnHelper.accessor((row) => row.token.name, {
    id: 'name',
    header: 'Name',
    cell: (info) => (
      <div className="flex items-center gap-2 font-semibold text-slate-900">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-indigo-100 bg-indigo-50 text-indigo-600">
          <Key className="h-4 w-4" />
        </div>
        {info.getValue()}
      </div>
    ),
  }),
  columnHelper.accessor((row) => row.token.client_id, {
    id: 'clientId',
    header: 'Client ID',
    cell: (info) => <span className="font-mono text-xs text-slate-500">{info.getValue()}</span>,
  }),
  columnHelper.accessor((row) => row.token.created_at, {
    id: 'createdAt',
    header: 'Created',
    cell: (info) => (
      <span className="text-xs text-slate-500">
        {formatDistanceToNow(parseISO(info.getValue()), { addSuffix: true })}
      </span>
    ),
  }),
  columnHelper.accessor((row) => row.token.last_used_at, {
    id: 'lastUsedAt',
    header: 'Last Used',
    cell: (info) => {
      const value = info.getValue();
      return (
        <span className="text-xs text-slate-500">
          {value ? formatDistanceToNow(parseISO(value), { addSuffix: true }) : '—'}
        </span>
      );
    },
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex justify-end">
        <TokenRowActions config={info.row.original.config} token={info.row.original.token} />
      </div>
    ),
  }),
];

// ─── Main Page ───────────────────────────────────────────────────────────────
export type ApiTokensPageProps = ApiTokenHookConfig;

/**
 * Platform-level API Tokens management page.
 *
 * Accepts explicit (baseUrl, tenantId, token) as props — usable by any app
 * in the monorepo (UCP Dashboard, IDP, IP, etc.) without needing an EDI provider.
 */
export function ApiTokensPage({
  baseUrl,
  tenantId,
  token,
  httpClient,
  logger,
}: ApiTokensPageProps) {
  const config = React.useMemo<ApiTokenHookConfig>(
    () => ({ baseUrl, tenantId, token, httpClient, logger }),
    [baseUrl, httpClient, logger, tenantId, token],
  );
  const { data: tokens = [], isLoading } = useApiTokensQuery(config);
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(null);

  const tableData = React.useMemo(
    () => tokens.map((t) => ({ token: t, config })),
    [tokens, config],
  );

  const table = useReactTable({
    data: tableData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
    getRowId: (row) => row.token.id,
  });

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col gap-10 pb-12 duration-700 ease-out">
      <section className="flex flex-col gap-2 border-b border-slate-200/60 pb-6">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-slate-900">
            <Key className="h-8 w-8 text-indigo-600" />
            API Tokens
          </h2>
          <CreateApiTokenDialog config={config} onCreated={setCreatedToken} />
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Generate and manage machine-to-machine API tokens for programmatic access.
        </p>
      </section>

      <DataTable
        table={table}
        columnsLength={columns.length}
        dataLength={tableData.length}
        isLoading={isLoading}
        ariaLabel="API tokens"
        emptyIcon={<Key className="h-10 w-10" />}
        emptyTitle="No API tokens yet"
        renderExpandedRow={(row) => <TokenDetails token={row.original.token} config={config} />}
      />

      {createdToken && (
        <TokenCredentialsModal token={createdToken} onClose={() => setCreatedToken(null)} />
      )}
    </div>
  );
}
