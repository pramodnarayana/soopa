import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { formatDistanceToNow, parseISO } from 'date-fns';
import {
  AlertTriangle,
  Check,
  Copy,
  Key,
  Loader2,
  Pencil,
  Plus,
  Power,
  Trash2,
} from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Button } from '../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import type { ApiTokenHookConfig } from './api/apiTokenHooks';
import {
  useApiTokensQuery,
  useCreateApiTokenMutation,
  useDeleteApiTokenMutation,
  useUpdateApiTokenMutation,
} from './api/apiTokenHooks';
import type { ApiToken, ApiTokenCreated } from './types';

// ─── Token Credentials Modal ────────────────────────────────────────────────
function TokenCredentialsModal({
  token,
  onClose,
}: {
  token: ApiTokenCreated;
  onClose: () => void;
}) {
  const [copiedId, setCopiedId] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedCombined, setCopiedCombined] = useState(false);

  const copyToClipboard = async (text: string, type: 'id' | 'secret' | 'combined') => {
    try {
      await navigator.clipboard.writeText(text);
      if (type === 'secret') {
        setCopiedSecret(true);
        setTimeout(() => setCopiedSecret(false), 2000);
      } else if (type === 'id') {
        setCopiedId(true);
        setTimeout(() => setCopiedId(false), 2000);
      } else {
        setCopiedCombined(true);
        setTimeout(() => setCopiedCombined(false), 2000);
      }
    } catch {
      // ignore clipboard error
    }
  };

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-xl">Token Generated Successfully</DialogTitle>
          <DialogDescription>
            Copy your client secret now. It will never be shown again.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-2 p-3 rounded-lg border border-amber-200 bg-amber-50 text-amber-900 text-sm">
          <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold text-amber-800">Store this secret securely</p>
            <p className="text-amber-700">
              If you lose this secret, you must generate a new token. We never store the raw secret.
            </p>
          </div>
        </div>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <span className="text-sm font-medium text-slate-700">Client ID</span>
            <div className="flex gap-2">
              <Input value={token.client_id} readOnly className="font-mono text-sm bg-slate-50" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.client_id, 'id')}
              >
                {copiedId ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <div className="grid gap-1.5">
            <span className="text-sm font-medium text-slate-700">Client Secret</span>
            <div className="flex gap-2">
              <Input
                value={token.token.split('.')[1] || ''}
                readOnly
                type="text"
                className="font-mono text-sm bg-slate-50"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.token.split('.')[1] || '', 'secret')}
              >
                {copiedSecret ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <div className="grid gap-1.5">
            <span className="text-sm font-medium text-slate-700">
              Combined Token (Bearer Token)
            </span>
            <div className="flex gap-2">
              <Input
                value={token.token}
                readOnly
                type="text"
                className="font-mono text-sm bg-slate-50"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.token, 'combined')}
              >
                {copiedCombined ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>

        <div className="p-4 mt-2 rounded-lg bg-indigo-50 border border-indigo-100 text-sm text-indigo-900">
          <p className="font-semibold text-indigo-950 mb-1">Developer Note: How to authenticate</p>
          <p className="text-indigo-800">
            Include the Combined Token in your HTTP requests using the standard Authorization
            header. If using Postman, select <strong>"Bearer Token"</strong> and paste the Combined
            Token exactly as is.
          </p>
          <code className="block mt-2 p-2.5 bg-white rounded border border-indigo-100 font-mono text-xs text-indigo-950">
            Authorization: Bearer {'<COMBINED_TOKEN>'}
          </code>
          <p className="text-xs text-indigo-700 mt-2 font-medium">
            Note: Do not manually type the word "Bearer" when using Postman's Auth tab, as Postman
            adds it automatically.
          </p>
        </div>

        <DialogFooter>
          <Button onClick={onClose}>I've saved the credentials</Button>
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
  config: ApiTokenHookConfig;
  onCreated: (token: ApiTokenCreated) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const createMutation = useCreateApiTokenMutation(config);

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const data = await createMutation.mutateAsync({ name: name.trim() });
      setOpen(false);
      setName('');
      onCreated(data);
    } catch {
      // surfaced by mutation
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button id="generate-api-token-btn" onClick={() => setOpen(true)}>
        <Plus className="w-4 h-4 mr-1" />
        Generate Token
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Key className="w-5 h-5 text-indigo-600" />
            Generate New API Token
          </DialogTitle>
          <DialogDescription>
            Create a new token for machine-to-machine integrations.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <Label htmlFor="new-token-name">Token Name</Label>
          <Input
            id="new-token-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. ERP Prod Integration"
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || createMutation.isPending}>
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
  config: ApiTokenHookConfig;
  token: ApiToken;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [confirmText, setConfirmText] = useState('');
  const deleteMutation = useDeleteApiTokenMutation(config);

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(token.id);
      setConfirmText('');
      onOpenChange(false);
    } catch {
      // surfaced by mutation
    }
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
          <code className="block bg-slate-100 rounded-lg px-3 py-2 text-xs font-mono break-all text-slate-700">
            {token.name}
          </code>
          <Label htmlFor={`delete-token-confirm-${token.id}`}>Confirmation</Label>
          <Input
            id={`delete-token-confirm-${token.id}`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Type token name to confirm"
            className="font-mono text-sm"
            autoComplete="off"
            aria-describedby={`delete-token-warning-${token.id}`}
          />
          <p id={`delete-token-warning-${token.id}`} className="sr-only">
            Warning: This action is permanent and irreversible. Any integrations using this token
            will immediately fail.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
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

// ─── Rename Token Dialog ─────────────────────────────────────────────────────
function RenameTokenDialog({
  config,
  token,
  open,
  onOpenChange,
}: {
  config: ApiTokenHookConfig;
  token: ApiToken;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState(token.name);
  const updateMutation = useUpdateApiTokenMutation(config);

  useEffect(() => {
    if (open) setName(token.name);
  }, [open, token.name]);

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
      // surfaced by mutation
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

// ─── Token Row Actions ───────────────────────────────────────────────────────
function TokenRowActions({ config, token }: { config: ApiTokenHookConfig; token: ApiToken }) {
  const [showDelete, setShowDelete] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const updateMutation = useUpdateApiTokenMutation(config);
  const isActive = token.active;

  const handleToggleActive = (e: React.MouseEvent) => {
    e.stopPropagation();
    updateMutation.mutate({ id: token.id, data: { active: !isActive } });
  };

  return (
    <>
      <div
        className="flex items-center gap-3 pr-4"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          role="switch"
          aria-checked={isActive}
          onClick={handleToggleActive}
          disabled={updateMutation.isPending}
          className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors ${
            isActive ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-100 border-slate-300'
          } ${updateMutation.isPending ? 'opacity-50 cursor-wait' : ''}`}
        >
          <span
            className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity ${isActive ? 'opacity-100 text-emerald-700' : 'opacity-0'}`}
          >
            Active
          </span>
          <span
            className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity ${isActive ? 'opacity-0' : 'opacity-100 text-slate-500'}`}
          >
            Inactive
          </span>
          <span
            className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow transition-transform ${isActive ? 'translate-x-[62px] bg-emerald-600 text-white' : 'translate-x-0 bg-white text-slate-400'}`}
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
            setShowRename(true);
          }}
          className="p-2 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors"
          title="Rename token"
          aria-label="Rename token"
        >
          <Pencil className="w-4 h-4" />
        </button>

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowDelete(true);
          }}
          className="p-2 text-red-600 bg-red-50 hover:bg-red-100 rounded-md transition-colors"
          title="Delete token"
          aria-label="Delete token"
        >
          <Trash2 className="w-4 h-4" />
        </button>
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
function TokenDetails({ token, config }: { token: ApiToken; config: ApiTokenHookConfig }) {
  const [name, setName] = useState(token.name);
  const updateMutation = useUpdateApiTokenMutation(config);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (trimmed && trimmed !== token.name) {
      try {
        await updateMutation.mutateAsync({ id: token.id, data: { name: trimmed } });
      } catch {
        // surfaced by mutation
      }
    }
  };

  return (
    <div className="p-4 bg-slate-50/50 border-b border-slate-100 text-sm text-slate-600 grid gap-8 md:grid-cols-2">
      <div className="grid gap-3">
        <div className="space-y-1">
          <Label htmlFor={`token-name-${token.id}`}>Token Name</Label>
          <div className="flex gap-2 max-w-sm">
            <Input
              id={`token-name-${token.id}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 text-sm bg-white"
            />
            <Button
              size="sm"
              className="h-8 shrink-0"
              onClick={handleSave}
              disabled={updateMutation.isPending || name.trim() === token.name || !name.trim()}
            >
              {updateMutation.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin mr-1" />
              ) : (
                <Check className="w-3 h-3 mr-1" />
              )}
              Save
            </Button>
          </div>
        </div>
      </div>
      <div className="grid gap-4 grid-cols-2 content-start pt-1">
        <div>
          <div className="font-semibold text-slate-900 mb-1">Client ID</div>
          <div className="font-mono text-xs text-slate-500 break-all">{token.client_id}</div>
        </div>
        <div>
          <div className="font-semibold text-slate-900 mb-1">Status</div>
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
        <div className="w-7 h-7 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100 shrink-0">
          <Key className="w-4 h-4" />
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
      <span className="text-slate-500 text-xs">
        {formatDistanceToNow(parseISO(info.getValue()), { addSuffix: true })}
      </span>
    ),
  }),
  columnHelper.accessor((row) => row.token.last_used_at, {
    id: 'lastUsedAt',
    header: 'Last Used',
    cell: (info) => (
      <span className="text-slate-500 text-xs">
        {info.getValue()
          ? formatDistanceToNow(parseISO(info.getValue() as string), { addSuffix: true })
          : '—'}
      </span>
    ),
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
export function ApiTokensPage({ baseUrl, tenantId, token }: ApiTokensPageProps) {
  const config = React.useMemo<ApiTokenHookConfig>(
    () => ({ baseUrl, tenantId, token }),
    [baseUrl, tenantId, token],
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
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Page Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
            <Key className="w-8 h-8 text-indigo-600" />
            API Tokens
          </h2>
          <CreateApiTokenDialog config={config} onCreated={setCreatedToken} />
        </div>
        <p className="text-slate-500 text-sm mt-1">
          Generate and manage machine-to-machine API tokens for programmatic access.
        </p>
      </section>

      {/* Token Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          Loading tokens…
        </div>
      ) : tokens.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-3">
          <Key className="w-10 h-10" />
          <p className="text-sm font-medium">No API tokens yet</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr
                  key={headerGroup.id}
                  className="border-b border-slate-100 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                >
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className={`pb-3 ${header.index === 0 ? 'pl-4' : ''}`}
                      style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-slate-50">
              {table.getRowModel().rows.map((row) => (
                <React.Fragment key={row.id}>
                  <tr
                    className="hover:bg-slate-50/50 transition-colors cursor-pointer group"
                    onClick={row.getToggleExpandedHandler()}
                  >
                    {row.getVisibleCells().map((cell, index) => (
                      <td key={cell.id} className={`py-3 ${index === 0 ? 'pl-4' : ''}`}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                  {row.getIsExpanded() && (
                    <tr>
                      <td
                        colSpan={row.getVisibleCells().length}
                        className="p-0 border-b border-slate-100"
                      >
                        <TokenDetails token={row.original.token} config={config} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Show credentials modal after creation */}
      {createdToken && (
        <TokenCredentialsModal token={createdToken} onClose={() => setCreatedToken(null)} />
      )}
    </div>
  );
}
