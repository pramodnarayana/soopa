import {
  type ApiProblem,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  DataTable,
  Input,
  Label,
  MonacoCodeViewer,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Compass, Database, Play, RefreshCw, RotateCcw, ShieldAlert } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery } from '../../application/use-catalog-queries';
import {
  useDeactivateConnectionMutation,
  useDiscoverCatalogMutation,
  useRelinkConnectionMutation,
} from '../../application/use-connection-queries';
import {
  useResetStreamCheckpointMutation,
  useStreamStatesQuery,
  useSyncRunsQuery,
  useTriggerSyncRunMutation,
} from '../../application/use-sync-run-queries';
import type { Connection, DiscoveredCatalog, StreamSchema } from '../../domain/connection';
import { SyncRunKind } from '../../domain/enums';
import type { StreamState, SyncRun } from '../../domain/sync-run';
import {
  formatBytesCompact,
  formatRelativeTimestamp,
  mapSyncRunStatusTone,
  stringifyJsonPretty,
} from '../shared/status-mapping';
import {
  isSecretConnectorProperty,
  SpecFormRenderer,
  splitSpecFormValues,
} from './SpecFormRenderer';

export function ConnectionOverviewTab({
  connection,
  onProblem,
  onDeactivated,
}: {
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onDeactivated: () => void;
}) {
  const [newName, setNewName] = useState(connection.name);
  const [secretValues, setSecretValues] = useState<Record<string, unknown>>({});
  const specView = useCatalogAppSpecQuery(connection.appId);
  const relinkMutation = useRelinkConnectionMutation(connection.id);
  const deactivateMutation = useDeactivateConnectionMutation(connection.id);

  const secretProps = useMemo(
    () => (specView.data?.properties ?? []).filter(isSecretConnectorProperty),
    [specView.data],
  );

  const handleRelink = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    onProblem(null);
    const { rawCredentials } = splitSpecFormValues(secretProps, secretValues);
    const hasSecretPatch = Object.keys(rawCredentials).length > 0;
    const res = await relinkMutation.mutateAsync({
      newName: newName.trim() || connection.name,
      updatedRawCredentials: hasSecretPatch ? rawCredentials : null,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    setSecretValues({});
    toast.success('Connection credentials & metadata re-linked.');
  };

  const handleDeactivate = async (): Promise<void> => {
    onProblem(null);
    const res = await deactivateMutation.mutateAsync();
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success('Connection soft-deactivated; historical traces preserved.');
    onDeactivated();
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Public Connector Configuration</CardTitle>
          <CardDescription>
            Secrets are AES-256-GCM encrypted in PostgreSQL and never returned over HTTP.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <CopyableIdPill
              value={connection.connectionFingerprint}
              prefixLabel="SHA-256"
              truncateLength={20}
            />
            {connection.lastRefreshedAt ? (
              <span className="text-muted-foreground">
                Refreshed {formatRelativeTimestamp(connection.lastRefreshedAt)}
              </span>
            ) : null}
          </div>
          <MonacoCodeViewer height={220} value={stringifyJsonPretty(connection.publicConfig)} />
        </CardContent>
      </Card>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Re-Link Credentials / Rename</CardTitle>
            <CardDescription>
              Rotate OAuth2 refresh tokens or API keys in-place without breaking bound
              Transformations or Stitches.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(e) => void handleRelink(e)} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="relink-conn-name">Display Name</Label>
                <Input
                  id="relink-conn-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
              </div>

              {secretProps.length > 0 ? (
                <SpecFormRenderer
                  properties={secretProps}
                  values={secretValues}
                  onChangeValue={(name, val) =>
                    setSecretValues((prev) => ({ ...prev, [name]: val }))
                  }
                />
              ) : null}

              <Button type="submit" size="sm" disabled={relinkMutation.isPending}>
                {relinkMutation.isPending ? 'Updating Vault...' : 'Save & Re-Link Connection'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="border-status-critical-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-status-critical-fg">
              <ShieldAlert className="h-4 w-4" />
              <span>Soft-Deactivate Connection</span>
            </CardTitle>
            <CardDescription>
              Halts pull syncs and outbound deliveries while retaining every L1→L5 audit record.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deactivateMutation.isPending || connection.deactivatedAt !== null}
              onClick={() => void handleDeactivate()}
            >
              {connection.deactivatedAt
                ? 'Already Deactivated'
                : deactivateMutation.isPending
                  ? 'Deactivating...'
                  : 'Soft-Deactivate Connection'}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function ConnectionCatalogTab({
  connectionId,
  onProblem,
  onConfigureTransformation,
}: {
  readonly connectionId: string;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onConfigureTransformation: () => void;
}) {
  const [discovered, setDiscovered] = useState<DiscoveredCatalog | null>(null);
  const discoverMutation = useDiscoverCatalogMutation(connectionId);

  const handleDiscover = async (): Promise<void> => {
    onProblem(null);
    const res = await discoverMutation.mutateAsync();
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    setDiscovered(res.value);
    toast.success(
      `Discovered ${res.value.streams.length} stream(s) (Catalog v${res.value.catalogVersion}).`,
    );
  };

  const streams = useMemo(() => [...(discovered?.streams ?? [])], [discovered]);

  const columns = useMemo<ColumnDef<StreamSchema>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Stream Name',
        cell: ({ row }) => <span className="font-mono font-semibold">{row.original.name}</span>,
      },
      {
        id: 'primaryKey',
        header: 'Primary Key',
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.primaryKey.join(', ') || '—'}</span>
        ),
      },
      {
        accessorKey: 'cursorField',
        header: 'Incremental Cursor',
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.cursorField ?? '—'}</span>
        ),
      },
      {
        id: 'syncModes',
        header: 'Supported Sync Modes',
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.supportedSyncModes.map((mode) => (
              <StatusBadge key={mode} label={mode} tone={StatusTone.NEUTRAL} />
            ))}
          </div>
        ),
      },
      {
        id: 'fieldsCount',
        header: 'Fields',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.fields.length}</span>
        ),
      },
      {
        id: 'actions',
        header: 'L3 Transformation',
        cell: () => (
          <Button type="button" variant="outline" size="sm" onClick={onConfigureTransformation}>
            Configure Transformer
          </Button>
        ),
      },
    ],
    [onConfigureTransformation],
  );

  const table = useReactTable({
    data: streams,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Discovered Source Schema Catalog</CardTitle>
          <CardDescription>
            Introspect live streams, primary keys, and incremental cursor capabilities directly from
            the connector.
          </CardDescription>
        </div>
        <Button
          type="button"
          size="sm"
          disabled={discoverMutation.isPending}
          onClick={() => void handleDiscover()}
          className="gap-1.5"
        >
          <Compass className="h-4 w-4" />
          <span>{discoverMutation.isPending ? 'Introspecting...' : 'Discover Schema Catalog'}</span>
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {discovered ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <CopyableIdPill
              value={discovered.catalogHash}
              prefixLabel="Catalog Hash"
              truncateLength={16}
            />
            <span>Version v{discovered.catalogVersion}</span>
          </div>
        ) : null}
        <DataTable
          table={table}
          columnsLength={columns.length}
          isLoading={discoverMutation.isPending}
          dataLength={streams.length}
          ariaLabel="Discovered connector streams"
          emptyIcon={<Database className="h-6 w-6" />}
          emptyTitle="Catalog Not Yet Introspected"
          emptyDescription="Click Discover Schema Catalog to fetch live stream schemas from the external endpoint."
        />
      </CardContent>
    </Card>
  );
}

export function ConnectionStreamsSyncTab({
  connectionId,
  onOpenTrace,
  onProblem,
}: {
  readonly connectionId: string;
  readonly onOpenTrace: (traceId: string) => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}) {
  const [manualStream, setManualStream] = useState('');
  const statesView = useStreamStatesQuery(connectionId);
  const runsView = useSyncRunsQuery(connectionId, 40);
  const triggerMutation = useTriggerSyncRunMutation(connectionId);
  const resetMutation = useResetStreamCheckpointMutation(connectionId);

  const handleTrigger = async (
    streamName: string,
    forcedKind: typeof SyncRunKind.INCREMENTAL | typeof SyncRunKind.FULL_REFRESH,
  ): Promise<void> => {
    const trimmed = streamName.trim();
    if (!trimmed) {
      return;
    }
    onProblem(null);
    const res = await triggerMutation.mutateAsync({ streamName: trimmed, forcedKind });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(`Triggered ${forcedKind} sync run ${res.value.runId} for "${trimmed}".`);
  };

  const handleReset = async (streamName: string): Promise<void> => {
    onProblem(null);
    const res = await resetMutation.mutateAsync(streamName);
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(`Reset stream checkpoint for "${streamName}".`);
  };

  const stateRows = useMemo(() => [...(statesView.data ?? [])], [statesView.data]);
  const runRows = useMemo(() => [...(runsView.data ?? [])], [runsView.data]);

  const stateColumns = useMemo<ColumnDef<StreamState>[]>(
    () => [
      {
        accessorKey: 'streamName',
        header: 'Stream',
        cell: ({ row }) => (
          <span className="font-mono font-semibold">{row.original.streamName}</span>
        ),
      },
      {
        accessorKey: 'cursorValue',
        header: 'Checkpoint Cursor',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.cursorField ?? 'cursor'}: {row.original.cursorValue ?? 'origin'}
          </span>
        ),
      },
      {
        accessorKey: 'recordsSyncedCount',
        header: 'Records Synced',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.recordsSyncedCount}</span>
        ),
      },
      {
        id: 'actions',
        header: 'Controls',
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={triggerMutation.isPending}
              onClick={() => void handleTrigger(row.original.streamName, SyncRunKind.INCREMENTAL)}
              className="gap-1"
            >
              <Play className="h-3.5 w-3.5" />
              <span>Incremental</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={triggerMutation.isPending}
              onClick={() => void handleTrigger(row.original.streamName, SyncRunKind.FULL_REFRESH)}
              className="gap-1"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Full Refresh</span>
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={resetMutation.isPending}
              onClick={() => void handleReset(row.original.streamName)}
              className="gap-1 text-status-critical-fg"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset Cursor</span>
            </Button>
          </div>
        ),
      },
    ],
    [triggerMutation.isPending, resetMutation.isPending],
  );

  const runColumns = useMemo<ColumnDef<SyncRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Sync Run',
        cell: ({ row }) => <CopyableIdPill value={row.original.runId} truncateLength={16} />,
      },
      {
        accessorKey: 'streamName',
        header: 'Stream & Gen',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.streamName} · Gen #{row.original.generationId} ({row.original.kind})
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapSyncRunStatusTone(row.original.status)}
          />
        ),
      },
      {
        id: 'metrics',
        header: 'Pages · Records · Bytes',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">
            {row.original.pagesCount}p · {row.original.recordsCount}r ·{' '}
            {formatBytesCompact(row.original.bytesCount)}
          </span>
        ),
      },
      {
        accessorKey: 'traceId',
        header: 'Audit Trace',
        cell: ({ row }) => <CopyableIdPill value={row.original.traceId} truncateLength={16} />,
      },
    ],
    [],
  );

  const stateTable = useReactTable({
    data: stateRows,
    columns: stateColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  const runTable = useReactTable({
    data: runRows,
    columns: runColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Ad-Hoc Pull Sync Trigger</CardTitle>
          <CardDescription>
            Launch an immediate incremental or full-refresh pull sync for any stream name.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2.5">
          <Input
            value={manualStream}
            onChange={(e) => setManualStream(e.target.value)}
            placeholder="Enter stream name (e.g. meter_readings, customers, invoices)..."
            className="max-w-sm font-mono text-sm"
          />
          <Button
            type="button"
            size="sm"
            disabled={!manualStream.trim() || triggerMutation.isPending}
            onClick={() => void handleTrigger(manualStream, SyncRunKind.INCREMENTAL)}
          >
            Trigger Incremental
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!manualStream.trim() || triggerMutation.isPending}
            onClick={() => void handleTrigger(manualStream, SyncRunKind.FULL_REFRESH)}
          >
            Trigger Full Refresh
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Stream Cursor Checkpoints</CardTitle>
          <CardDescription>
            Durable watermarks committed only after L2 replica persistence.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable
            table={stateTable}
            columnsLength={stateColumns.length}
            isLoading={statesView.isLoading}
            dataLength={stateRows.length}
            ariaLabel="Stream sync checkpoints"
            emptyIcon={<Database className="h-6 w-6" />}
            emptyTitle="No Checkpoints Recorded Yet"
            emptyDescription="Trigger your first stream pull sync above to initialize cursor watermarks."
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pull Sync Run History (Live Polling)</CardTitle>
          <CardDescription>Click any sync run to open its L1→L5 Trace Waterfall.</CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable
            table={runTable}
            columnsLength={runColumns.length}
            isLoading={runsView.isLoading}
            dataLength={runRows.length}
            ariaLabel="Pull sync execution runs"
            emptyIcon={<RefreshCw className="h-6 w-6" />}
            emptyTitle="No Pull Sync Runs Executed"
            onRowClick={(row) => onOpenTrace(row.original.traceId)}
          />
        </CardContent>
      </Card>
    </div>
  );
}
