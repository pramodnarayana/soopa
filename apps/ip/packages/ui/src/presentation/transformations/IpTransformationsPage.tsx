import {
  type ApiProblem,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { ArrowUpCircle, GitMerge, Plus } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import {
  useBindStreamTransformationMutation,
  useConnectionTransformationsQuery,
  usePromoteShadowTransformationMutation,
  useRegisteredTransformersQuery,
} from '../../application/use-transformation-queries';
import {
  isTransformationModeValue,
  TransformationMode,
  type TransformationModeValue,
} from '../../domain/enums';
import type {
  BindStreamTransformationInput,
  RegisteredTransformer,
  Transformation,
} from '../../domain/transformation';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { mapTransformationModeTone } from '../shared/status-mapping';
import { TransformationWorkbenchPanel } from './TransformationWorkbenchPanel';

export interface IpTransformationsPageProps {
  readonly initialConnectionId?: string;
}

function buildBindTransformationPayload(params: {
  transformationId: string;
  version: string;
  mode: TransformationModeValue;
  shadowVer: string;
}): BindStreamTransformationInput {
  const parsedShadow = params.shadowVer.trim() ? Number(params.shadowVer) : null;
  const validShadow =
    params.mode === TransformationMode.SHADOW &&
    parsedShadow !== null &&
    !Number.isNaN(parsedShadow)
      ? parsedShadow
      : null;

  return {
    transformationId: params.transformationId,
    transformationVersion: Number(params.version) || 1,
    mode: params.mode,
    shadowTransformationVersion: validShadow,
  };
}

function ConfigureTransformationModal({
  open,
  onOpenChange,
  connectionId,
  transformers,
  onProblem,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly connectionId: string;
  readonly transformers: readonly RegisteredTransformer[];
  readonly onProblem: (problem: ApiProblem | null) => void;
}) {
  const defaultId = transformers[0]?.transformationId ?? '';
  const defaultVer = String(transformers[0]?.transformationVersion ?? 1);
  const [stream, setStream] = useState('meter_readings');
  const [transformationId, setTransformationId] = useState(defaultId);
  const [version, setVersion] = useState(defaultVer);
  const [mode, setMode] = useState<TransformationModeValue>(TransformationMode.ACTIVE);
  const [shadowVer, setShadowVer] = useState('');
  const bindMutation = useBindStreamTransformationMutation();

  const effectiveId = transformationId || defaultId;
  const trimmedStream = stream.trim();

  const handleSave = async (): Promise<void> => {
    onProblem(null);
    const res = await bindMutation.mutateAsync({
      connectionId,
      stream: trimmedStream,
      input: buildBindTransformationPayload({
        transformationId: effectiveId,
        version,
        mode,
        shadowVer,
      }),
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(`Configured L3 Transformation for stream "${res.value.stream}".`);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Configure Stream L3 Transformation</DialogTitle>
          <DialogDescription>
            Attach a versioned code Transformer to normalize L2 replica records into canonical L3
            entities.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cfg-stream-name">Source Stream Name</Label>
            <Input
              id="cfg-stream-name"
              value={stream}
              onChange={(e) => setStream(e.target.value)}
              className="font-mono text-sm"
            />
          </div>

          <div className="space-y-1.5">
            <Label>Registered Code Transformer</Label>
            <Select value={effectiveId} onValueChange={setTransformationId}>
              <SelectTrigger aria-label="Select code transformer">
                <SelectValue placeholder="Choose transformer" />
              </SelectTrigger>
              <SelectContent>
                {transformers.map((tr) => (
                  <SelectItem
                    key={`${tr.transformationId}:${tr.transformationVersion}`}
                    value={tr.transformationId}
                  >
                    {tr.transformationId} (v{tr.transformationVersion})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="cfg-tr-ver">Active Version</Label>
              <Input
                id="cfg-tr-ver"
                type="number"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Execution Mode</Label>
              <Select
                value={mode}
                onValueChange={(v) => {
                  if (isTransformationModeValue(v)) {
                    setMode(v);
                  }
                }}
              >
                <SelectTrigger aria-label="Select transformation mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={TransformationMode.ACTIVE}>ACTIVE</SelectItem>
                  <SelectItem value={TransformationMode.SHADOW}>SHADOW (Dual Eval)</SelectItem>
                  <SelectItem value={TransformationMode.DISABLED}>DISABLED</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {mode === TransformationMode.SHADOW ? (
            <div className="space-y-1.5">
              <Label htmlFor="cfg-shadow-ver">Shadow Candidate Version</Label>
              <Input
                id="cfg-shadow-ver"
                type="number"
                value={shadowVer}
                onChange={(e) => setShadowVer(e.target.value)}
                placeholder="2"
              />
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={bindMutation.isPending || !effectiveId || !trimmedStream}
            onClick={() => void handleSave()}
          >
            {bindMutation.isPending ? 'Saving...' : 'Save Transformation'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StreamTransformationsTable({
  items,
  isLoading,
  isPromoting,
  onPromote,
}: {
  readonly items: readonly Transformation[];
  readonly isLoading: boolean;
  readonly isPromoting: boolean;
  readonly onPromote: (stream: string) => void;
}) {
  const rows = useMemo(() => [...items], [items]);
  const columns = useMemo<ColumnDef<Transformation>[]>(
    () => [
      {
        accessorKey: 'stream',
        header: 'Source Stream',
        cell: ({ row }) => <span className="font-mono font-semibold">{row.original.stream}</span>,
      },
      {
        accessorKey: 'transformationId',
        header: 'Code Transformer',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.transformationId} (v{row.original.transformationVersion})
          </span>
        ),
      },
      {
        accessorKey: 'mode',
        header: 'Mode',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.mode}
            tone={mapTransformationModeTone(row.original.mode)}
          />
        ),
      },
      {
        accessorKey: 'shadowTransformationVersion',
        header: 'Shadow Candidate',
        cell: ({ row }) =>
          row.original.shadowTransformationVersion !== null ? (
            <StatusBadge
              label={`Candidate v${row.original.shadowTransformationVersion}`}
              tone={StatusTone.SHADOW}
            />
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        id: 'promote',
        header: 'Cutover',
        cell: ({ row }) =>
          row.original.shadowTransformationVersion !== null ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isPromoting}
              onClick={() => onPromote(row.original.stream)}
              className="gap-1.5"
            >
              <ArrowUpCircle className="h-3.5 w-3.5 text-brand-ink" />
              <span>Promote v{row.original.shadowTransformationVersion}</span>
            </Button>
          ) : null,
      },
    ],
    [isPromoting, onPromote],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      columnsLength={columns.length}
      isLoading={isLoading}
      dataLength={rows.length}
      ariaLabel="Configured stream transformations"
      emptyIcon={<GitMerge className="h-6 w-6" />}
      emptyTitle="No Stream Transformations Configured"
      emptyDescription="Configure a stream Transformation above or test sample JSON in the Dry-Run Workbench below."
    />
  );
}

function firstNonNullProblem(
  ...problems: ReadonlyArray<ApiProblem | null | undefined>
): ApiProblem | null {
  for (const item of problems) {
    if (item) {
      return item;
    }
  }
  return null;
}

export function IpTransformationsPage({ initialConnectionId = '' }: IpTransformationsPageProps) {
  const connectionsView = useConnectionsQuery();
  const transformersView = useRegisteredTransformersQuery();
  const connections = connectionsView.data ?? [];
  const transformers = transformersView.data ?? [];

  const [selectedConnectionId, setSelectedConnectionId] = useState(initialConnectionId);
  const [configureOpen, setConfigureOpen] = useState(false);
  const [actionProblem, setActionProblem] = useState<ApiProblem | null>(null);

  const fallbackConnectionId = connections[0] ? connections[0].id : '';
  const effectiveConnectionId = selectedConnectionId || fallbackConnectionId;
  const transformationsView = useConnectionTransformationsQuery(effectiveConnectionId || null);
  const promoteMutation = usePromoteShadowTransformationMutation();

  const handlePromote = async (stream: string): Promise<void> => {
    setActionProblem(null);
    const res = await promoteMutation.mutateAsync({
      connectionId: effectiveConnectionId,
      stream,
    });
    if (!res.ok) {
      setActionProblem(res.error);
      return;
    }
    toast.success(
      `Promoted "${stream}" from v${res.value.previousVersion} to v${res.value.promotedVersion}!`,
    );
  };

  const bannerProblem = firstNonNullProblem(
    actionProblem,
    connectionsView.problem,
    transformersView.problem,
    transformationsView.problem,
  );

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="L2 → L3 Canonical Normalization"
        title="Transformations & Shadow Diff Workbench"
        subtitle="Attach versioned code Transformers to source streams, run non-mutating shadow candidates in parallel, and promote verified upgrades in one click."
        actions={
          <Button
            type="button"
            size="sm"
            disabled={!effectiveConnectionId}
            onClick={() => setConfigureOpen(true)}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" />
            <span>Configure Stream Transformation</span>
          </Button>
        }
      />

      <ApiProblemBanner problem={bannerProblem} />

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Active Connection Scope</CardTitle>
            <CardDescription>Registered code Transformers ({transformers.length})</CardDescription>
          </div>
          <div className="w-72">
            <Select value={effectiveConnectionId} onValueChange={setSelectedConnectionId}>
              <SelectTrigger aria-label="Select connection for transformations">
                <SelectValue placeholder="Select a connection..." />
              </SelectTrigger>
              <SelectContent>
                {connections.map((conn) => (
                  <SelectItem key={conn.id} value={conn.id}>
                    {conn.name} ({conn.appId})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <StreamTransformationsTable
            items={transformationsView.data ?? []}
            isLoading={transformationsView.isLoading}
            isPromoting={promoteMutation.isPending}
            onPromote={(stream) => void handlePromote(stream)}
          />
        </CardContent>
      </Card>

      <TransformationWorkbenchPanel
        connectionId={effectiveConnectionId}
        transformers={transformers}
      />

      <ConfigureTransformationModal
        open={configureOpen}
        onOpenChange={setConfigureOpen}
        connectionId={effectiveConnectionId}
        transformers={transformers}
        onProblem={setActionProblem}
      />
    </div>
  );
}
