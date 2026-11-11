import {
  ApiErrorCode,
  type ApiProblem,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  type Result,
  SearchableSelect,
  type SearchableSelectOption,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui';
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  Check,
  ChevronDown,
  ChevronRight,
  Compass,
  Copy,
  Database,
  Play,
  Radio,
  Search,
  ShieldAlert,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery } from '../../application/use-catalog-queries';
import {
  useConnectionCatalogQuery,
  useDeactivateConnectionMutation,
  useDeleteConnectionMutation,
  useDiscoverCatalogMutation,
  useRelinkConnectionMutation,
  useSimulatePushMutation,
  useUpdateConnectionMutation,
} from '../../application/use-connection-queries';
import { useSimulatorEntitiesQuery } from '../../application/use-simulator-queries';
import {
  useStreamStatesQuery,
  useSyncRunsQuery,
  useTriggerSyncRunMutation,
} from '../../application/use-sync-run-queries';
import {
  buildIngressWebhookUrl,
  type Connection,
  type DiscoveredCatalog,
  type StreamSchema,
} from '../../domain/connection';
import {
  ConnectionStatus,
  ConnectorPropertyKey,
  SyncRunKind,
  SyncRunStatus,
  UNIVERSAL_SIMULATOR_APP_ID,
} from '../../domain/enums';
import type { StreamState, SyncRun } from '../../domain/sync-run';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { formatRelativeTimestamp, mapSyncRunStatusTone } from '../shared/status-mapping';
import {
  isPropertyVisible,
  isSecretConnectorProperty,
  resolvePropertyLabel,
  SingleSpecPropertyControl,
  splitSpecFormValues,
} from './SpecFormRenderer';

const EntityRowLocalStatus = {
  UNSYNCED: 'UNSYNCED',
  UNKNOWN: 'UNKNOWN',
} as const;

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function ConnectionOverviewTab({
  connection,
  onProblem,
  onDeactivated,
  onDeleted,
}: {
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onDeactivated: () => void;
  readonly onDeleted?: () => void;
}) {
  const [name, setName] = useState(connection.name);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const specView = useCatalogAppSpecQuery(connection.appId);
  const relinkMutation = useRelinkConnectionMutation(connection.id);
  const updateMutation = useUpdateConnectionMutation(connection.id);
  const deactivateMutation = useDeactivateConnectionMutation(connection.id);
  const deleteMutation = useDeleteConnectionMutation(connection.id);
  const isDeactivated = connection.status === ConnectionStatus.DEACTIVATED;
  const isSaving = relinkMutation.isPending || updateMutation.isPending;

  const allProperties = specView.data?.properties ?? [];

  const [formValues, setFormValues] = useState<Record<string, unknown>>(() => ({
    ...connection.publicConfig,
    [ConnectorPropertyKey.AUTH_TYPE]: connection.authType,
  }));

  const visibleProperties = useMemo(
    () => allProperties.filter((prop) => isPropertyVisible(prop, formValues, allProperties)),
    [allProperties, formValues],
  );

  const isDirty = useMemo(() => {
    if (name.trim() !== connection.name) return true;
    if (formValues[ConnectorPropertyKey.AUTH_TYPE] !== connection.authType) return true;
    for (const [key, val] of Object.entries(formValues)) {
      if (key === ConnectorPropertyKey.AUTH_TYPE) continue;
      if (val !== connection.publicConfig[key]) return true;
    }
    for (const key of Object.keys(connection.publicConfig)) {
      if (key === ConnectorPropertyKey.AUTH_TYPE) continue;
      if (!(key in formValues) || formValues[key] === '' || formValues[key] === undefined) {
        if (connection.publicConfig[key] !== undefined && connection.publicConfig[key] !== '') {
          return true;
        }
      }
    }
    return false;
  }, [name, formValues, connection]);

  const handleSave = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    onProblem(null);

    const { rawCredentials } = splitSpecFormValues(allProperties, formValues);
    const hasSecretPatch = Object.keys(rawCredentials).length > 0;

    // Preserve unexposed public config keys and omit cleared keys
    const mergedPublicConfig: Record<string, unknown> = {
      ...connection.publicConfig,
    };
    for (const prop of allProperties) {
      if (isSecretConnectorProperty(prop)) continue;
      const val = formValues[prop.name];
      if (val === undefined || val === '') {
        delete mergedPublicConfig[prop.name];
      } else {
        mergedPublicConfig[prop.name] = val;
      }
    }
    if (formValues[ConnectorPropertyKey.AUTH_TYPE]) {
      mergedPublicConfig[ConnectorPropertyKey.AUTH_TYPE] =
        formValues[ConnectorPropertyKey.AUTH_TYPE];
    }

    const mutation = isDeactivated ? relinkMutation : updateMutation;
    const res = await mutation.mutateAsync({
      newName: name.trim() || connection.name,
      updatedRawCredentials: hasSecretPatch ? rawCredentials : null,
      updatedPublicConfig: Object.keys(mergedPublicConfig).length > 0 ? mergedPublicConfig : null,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(isDeactivated ? 'Connection updated and reactivated.' : 'Connection updated.');
  };

  const handleDeactivate = async (): Promise<void> => {
    onProblem(null);
    const res = await deactivateMutation.mutateAsync();
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success('Connection deactivated.');
    onDeactivated();
  };

  const handleDelete = async (): Promise<void> => {
    onProblem(null);
    const res = await deleteMutation.mutateAsync(connection.id);
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success('Connection deleted. Historical entities and synced data preserved.');
    setDeleteDialogOpen(false);
    onDeleted?.();
  };

  const statusTone =
    connection.status === ConnectionStatus.ACTIVE
      ? StatusTone.HEALTHY
      : connection.status === ConnectionStatus.PENDING_AUTH
        ? StatusTone.WARNING
        : StatusTone.NEUTRAL;

  return (
    <div className="p-6 bg-muted/20 rounded-xl border border-border">
      <form onSubmit={(e) => void handleSave(e)} className="space-y-6">
        <div className="flex justify-between items-center pb-4 border-b border-border">
          <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
            Connection Details
          </h4>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={isSaving || !isDirty} className="text-xs">
              {isSaving ? 'Saving...' : 'Save Changes'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={deactivateMutation.isPending || connection.deactivatedAt !== null}
              onClick={() => void handleDeactivate()}
              className="text-xs"
            >
              {connection.deactivatedAt
                ? 'Already Deactivated'
                : deactivateMutation.isPending
                  ? 'Deactivating...'
                  : 'Deactivate Connection'}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setDeleteDialogOpen(true)}
              className="text-xs"
            >
              Delete Connection
            </Button>
          </div>
        </div>

        {/* Editable form fields first, starting with Name */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="space-y-2">
            <Label htmlFor="conn-name">Name</Label>
            <Input
              id="conn-name"
              name="connection_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {visibleProperties.map((prop) => {
            const displayLabel = resolvePropertyLabel(prop, connection.authType);
            return (
              <div key={prop.name} className="space-y-2">
                <Label htmlFor={`spec-${prop.name}`} className="flex items-center gap-1">
                  <span>{displayLabel}</span>
                  {prop.required && !isSecretConnectorProperty(prop) ? (
                    <span className="text-status-critical-fg">*</span>
                  ) : null}
                  {prop.required && isSecretConnectorProperty(prop) ? (
                    <span className="text-xs font-normal text-muted-foreground">(stored)</span>
                  ) : null}
                </Label>
                <SingleSpecPropertyControl
                  prop={prop}
                  rawValue={formValues[prop.name]}
                  onChange={(nextVal) =>
                    setFormValues((prev) => ({ ...prev, [prop.name]: nextVal }))
                  }
                  currentAuthType={connection.authType}
                  isEditing={true}
                />
              </div>
            );
          })}
        </div>

        {/* Readonly fields arranged after editable fields */}
        <div className="grid grid-cols-2 gap-6 text-xs sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Connector</Label>
            <div className="font-semibold text-sm text-foreground">
              {specView.data?.displayName || connection.appId}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <div>
              <StatusBadge label={connection.status} tone={statusTone} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Auth Strategy</Label>
            <div className="font-mono text-sm text-foreground">{connection.authType}</div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Created</Label>
            <div className="text-sm text-foreground">
              {formatRelativeTimestamp(connection.createdAt)}
            </div>
          </div>
          {connection.lastRefreshedAt ? (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Last Refreshed</Label>
              <div className="text-sm text-foreground">
                {formatRelativeTimestamp(connection.lastRefreshedAt)}
              </div>
            </div>
          ) : null}
        </div>
      </form>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Connection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{' '}
              <span className="font-semibold text-foreground">{connection.name}</span>? Historical
              entities and synced data will remain preserved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setDeleteDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => void handleDelete()}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete Connection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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

export interface ConnectionEntitiesSyncTabProps {
  readonly connectionId: string;
  readonly connection?: Connection;
  readonly onInspectEntity?: (entityName: string) => void;
  readonly onOpenTrace: (traceId: string) => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}

const SCHEDULE_OPTIONS: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'manual', label: 'Manual' },
  { value: '5m', label: 'Every 5 minutes' },
  { value: '15m', label: 'Every 15 minutes' },
  { value: '1h', label: 'Hourly' },
  { value: '6h', label: 'Every 6 hours' },
  { value: '24h', label: 'Daily' },
];

const SYNC_FROM_OPTIONS: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'all', label: 'All' },
  { value: '30d', label: 'Last 30 Days' },
  { value: '7d', label: 'Last 7 Days' },
  { value: '24h', label: 'Last 24 Hours' },
  { value: 'custom', label: 'Specific Date' },
];

interface EntityRow {
  readonly streamName: string;
  readonly canonical: string;
  readonly status: string;
  readonly syncMode: string;
  readonly cursorField: string | null;
  readonly cursorValue: string | null;
  readonly recordsSyncedCount: number;
  readonly lastSyncedAt: string | null;
}

export interface StreamScheduleMutationInput {
  readonly newName: string;
  readonly updatedPublicConfig: Record<string, unknown>;
}

export async function commitStreamScheduleConfigUpdate(params: {
  readonly connection: Connection | undefined;
  readonly nextSchedules: Record<string, string>;
  readonly nextSyncFrom: Record<string, string>;
  readonly mutateUpdate: (
    input: StreamScheduleMutationInput,
  ) => Promise<Result<Connection, ApiProblem>>;
  readonly onProblem: (problem: ApiProblem | null) => void;
}): Promise<boolean> {
  const { connection, nextSchedules, nextSyncFrom, mutateUpdate, onProblem } = params;
  if (!connection) return false;
  onProblem(null);
  const allKeys = new Set([...Object.keys(nextSchedules), ...Object.keys(nextSyncFrom)]);
  const serializedSchedules: Record<string, { schedule: string; sync_from: string }> = {};
  for (const key of allKeys) {
    serializedSchedules[key] = {
      schedule: nextSchedules[key] ?? '15m',
      sync_from: nextSyncFrom[key] ?? 'all',
    };
  }
  const res = await mutateUpdate({
    newName: connection.name,
    updatedPublicConfig: {
      ...connection.publicConfig,
      stream_schedules: serializedSchedules,
    },
  });
  if (!res.ok) {
    onProblem(res.error);
    return false;
  }
  return true;
}

export function reconcileSelectedStreamNames(
  previous: Set<string>,
  validStreamNames: ReadonlySet<string>,
  newlyAddedStreams: readonly string[],
): Set<string> {
  let mutated = false;
  const next = new Set<string>();
  for (const name of previous) {
    if (validStreamNames.has(name)) {
      next.add(name);
    } else {
      mutated = true;
    }
  }
  for (const added of newlyAddedStreams) {
    if (validStreamNames.has(added) && !next.has(added)) {
      next.add(added);
      mutated = true;
    }
  }
  return mutated ? next : previous;
}

export function ConnectionEntitiesSyncTab({
  connectionId,
  connection,
  onInspectEntity,
  onOpenTrace,
  onProblem,
}: ConnectionEntitiesSyncTabProps) {
  const { baseUrl, tenantId } = useIpWorkspace();
  const [search, setSearch] = useState('');
  const [userSelectedStreams, setUserSelectedStreams] = useState<string[]>([]);
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [copiedStreamWebhook, setCopiedStreamWebhook] = useState<string | null>(null);
  const [streamSyncFrom, setStreamSyncFrom] = useState<Record<string, string>>({});
  const [streamCustomDates, setStreamCustomDates] = useState<Record<string, string>>({});
  const [streamSchedules, setStreamSchedules] = useState<Record<string, string>>({});
  const [expandedStreams, setExpandedStreams] = useState<Set<string>>(new Set());
  const [hasDiscoveredEmpty, setHasDiscoveredEmpty] = useState(false);

  const isAuthPending = connection?.status === ConnectionStatus.PENDING_AUTH;
  const isSimulator = connection?.appId === UNIVERSAL_SIMULATOR_APP_ID;

  const catalogView = useConnectionCatalogQuery(connectionId, false);
  const simulatorEntitiesView = useSimulatorEntitiesQuery(connectionId, Boolean(isSimulator));
  const statesView = useStreamStatesQuery(connectionId);
  const runsView = useSyncRunsQuery(connectionId, 40);
  const triggerMutation = useTriggerSyncRunMutation(connectionId);
  const discoverMutation = useDiscoverCatalogMutation(connectionId);
  const updateConnectionMutation = useUpdateConnectionMutation(connectionId);
  const simulatePushMutation = useSimulatePushMutation(connectionId);

  // Hydrate persisted stream schedules from connection.publicConfig.stream_schedules
  React.useEffect(() => {
    const rawSchedules = connection?.publicConfig?.stream_schedules;
    if (isPlainRecord(rawSchedules)) {
      const nextSchedules: Record<string, string> = {};
      const nextSyncFrom: Record<string, string> = {};
      for (const [sName, val] of Object.entries(rawSchedules)) {
        if (typeof val === 'string') {
          nextSchedules[sName] = val;
        } else if (isPlainRecord(val)) {
          if (typeof val.schedule === 'string') nextSchedules[sName] = val.schedule;
          if (typeof val.sync_from === 'string') nextSyncFrom[sName] = val.sync_from;
        }
      }
      setStreamSchedules((prev) => ({ ...nextSchedules, ...prev }));
      setStreamSyncFrom((prev) => ({ ...nextSyncFrom, ...prev }));
    }
  }, [connection?.publicConfig?.stream_schedules]);

  // Build entity rows from recorded stream states, simulator entities, and user-selected entities
  const entityRows = useMemo<EntityRow[]>(() => {
    const statesMap = new Map<string, StreamState>();
    for (const st of statesView.data ?? []) {
      statesMap.set(st.streamName, st);
    }

    const latestRunByStream = new Map<string, SyncRun>();
    for (const run of runsView.data ?? []) {
      if (!latestRunByStream.has(run.streamName)) {
        latestRunByStream.set(run.streamName, run);
      }
    }

    const seenStreams = new Set<string>();
    const rows: EntityRow[] = [];

    // 1. Add any streams already recorded in statesView (previously synced)
    for (const [sName, state] of statesMap.entries()) {
      seenStreams.add(sName);
      const latestRun = latestRunByStream.get(sName);
      const status = latestRun
        ? latestRun.status
        : state.lastSyncedAt
          ? SyncRunStatus.SUCCEEDED
          : EntityRowLocalStatus.UNKNOWN;
      rows.push({
        streamName: sName,
        canonical: 'CANONICAL_RECORD',
        status,
        syncMode: SyncRunKind.INCREMENTAL,
        cursorField: state.cursorField ?? null,
        cursorValue: state.cursorValue ?? null,
        recordsSyncedCount: state.recordsSyncedCount,
        lastSyncedAt: state.lastSyncedAt ?? null,
      });
    }

    // 2. For Simulator connections, display configured simulator entities immediately
    if (isSimulator) {
      for (const simEnt of simulatorEntitiesView.data ?? []) {
        if (!seenStreams.has(simEnt.entityName)) {
          seenStreams.add(simEnt.entityName);
          rows.push({
            streamName: simEnt.entityName,
            canonical: 'CANONICAL_RECORD',
            status: EntityRowLocalStatus.UNSYNCED,
            syncMode: SyncRunKind.INCREMENTAL,
            cursorField: simEnt.cursorField,
            cursorValue: null,
            recordsSyncedCount: 0,
            lastSyncedAt: null,
          });
        }
      }
    }

    // 3. Add user-selected entities (explicitly added from discovered catalog or picker)
    for (const sName of userSelectedStreams) {
      if (!seenStreams.has(sName)) {
        seenStreams.add(sName);
        const catalogStream = catalogView.data?.streams.find((s) => s.name === sName);
        rows.push({
          streamName: sName,
          canonical: 'CANONICAL_RECORD',
          status: EntityRowLocalStatus.UNSYNCED,
          syncMode: catalogStream?.supportedSyncModes[0] ?? SyncRunKind.INCREMENTAL,
          cursorField: catalogStream?.cursorField ?? null,
          cursorValue: null,
          recordsSyncedCount: 0,
          lastSyncedAt: null,
        });
      }
    }

    return rows;
  }, [
    statesView.data,
    runsView.data,
    isSimulator,
    simulatorEntitiesView.data,
    userSelectedStreams,
    catalogView.data?.streams,
  ]);

  // Active stream names (already in the table)
  const activeStreamNames = useMemo(() => {
    const set = new Set<string>();
    for (const row of entityRows) {
      set.add(row.streamName);
    }
    return set;
  }, [entityRows]);

  // Available discovered streams from external app that haven't been added to the table yet
  const availableDiscoveredOptions = useMemo<readonly SearchableSelectOption[]>(() => {
    const catalogStreams = catalogView.data?.streams ?? [];
    return catalogStreams
      .filter((st) => !activeStreamNames.has(st.name))
      .map((st) => ({
        value: st.name,
        label: (
          <div className="flex items-center justify-between w-full">
            <span className="font-mono text-xs font-semibold">{st.name}</span>
            <span className="text-[10px] text-muted-foreground uppercase ml-2">
              {st.supportedSyncModes[0] ?? 'SYNC'}
            </span>
          </div>
        ),
        searchString: st.name,
      }));
  }, [catalogView.data?.streams, activeStreamNames]);

  // Selection state (selected stream names for batch sync)
  const [selectedStreams, setSelectedStreams] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const row of entityRows) {
      if (row.recordsSyncedCount > 0 || isSimulator) {
        initial.add(row.streamName);
      }
    }
    return initial;
  });

  const initializedStatesRef = React.useRef(false);
  React.useEffect(() => {
    if (!initializedStatesRef.current && (statesView.data?.length ?? 0) > 0) {
      initializedStatesRef.current = true;
      setSelectedStreams((prev) => {
        const next = new Set(prev);
        for (const st of statesView.data ?? []) {
          next.add(st.streamName);
        }
        return next;
      });
    }
  }, [statesView.data]);

  const seenSimulatorStreamsRef = React.useRef<Set<string>>(
    new Set(isSimulator ? (simulatorEntitiesView.data ?? []).map((e) => e.entityName) : []),
  );
  React.useEffect(() => {
    const currentSimNames = isSimulator
      ? (simulatorEntitiesView.data ?? []).map((e) => e.entityName)
      : [];
    const newlyAddedSim = currentSimNames.filter((n) => !seenSimulatorStreamsRef.current.has(n));
    seenSimulatorStreamsRef.current = new Set(currentSimNames);
    if (newlyAddedSim.length > 0) {
      setHasDiscoveredEmpty(false);
    }
    setSelectedStreams((prev) =>
      reconcileSelectedStreamNames(prev, activeStreamNames, newlyAddedSim),
    );
  }, [activeStreamNames, isSimulator, simulatorEntitiesView.data]);

  const handleSelectDiscoveredEntity = (streamName: string) => {
    const trimmed = streamName.trim();
    if (!trimmed || activeStreamNames.has(trimmed)) return;
    setUserSelectedStreams((prev) => [...prev, trimmed]);
    setSelectedStreams((prev) => new Set([...prev, trimmed]));
    toast.success(`Added "${trimmed}" to entities table.`);
  };

  const filteredEntityRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entityRows;
    return entityRows.filter(
      (r) => r.streamName.toLowerCase().includes(q) || r.canonical.toLowerCase().includes(q),
    );
  }, [entityRows, search]);

  const allVisibleSelected =
    filteredEntityRows.length > 0 &&
    filteredEntityRows.every((r) => selectedStreams.has(r.streamName));

  const toggleSelectAll = () => {
    if (allVisibleSelected) {
      const next = new Set(selectedStreams);
      for (const r of filteredEntityRows) {
        next.delete(r.streamName);
      }
      setSelectedStreams(next);
    } else {
      const next = new Set(selectedStreams);
      for (const r of filteredEntityRows) {
        next.add(r.streamName);
      }
      setSelectedStreams(next);
    }
  };

  const toggleStream = (streamName: string) => {
    const next = new Set(selectedStreams);
    if (next.has(streamName)) {
      next.delete(streamName);
    } else {
      next.add(streamName);
    }
    setSelectedStreams(next);
  };

  const toggleRowExpanded = (streamName: string) => {
    setExpandedStreams((prev) => {
      const next = new Set(prev);
      if (next.has(streamName)) {
        next.delete(streamName);
      } else {
        next.add(streamName);
      }
      return next;
    });
  };

  const persistStreamScheduleConfig = async (
    nextSchedules: Record<string, string>,
    nextSyncFrom: Record<string, string>,
  ): Promise<boolean> =>
    commitStreamScheduleConfigUpdate({
      connection,
      nextSchedules,
      nextSyncFrom,
      mutateUpdate: (input) => updateConnectionMutation.mutateAsync(input),
      onProblem,
    });

  const handleSyncFromChange = async (streamName: string, syncFrom: string): Promise<void> => {
    const previousSyncFrom = streamSyncFrom;
    const nextSyncFrom = { ...streamSyncFrom, [streamName]: syncFrom };
    setStreamSyncFrom(nextSyncFrom);
    const saved = await persistStreamScheduleConfig(streamSchedules, nextSyncFrom);
    if (!saved) {
      setStreamSyncFrom(previousSyncFrom);
      return;
    }
    const match = SYNC_FROM_OPTIONS.find((b) => b.value === syncFrom);
    toast.success(`Sync from for "${streamName}" set to ${match?.label ?? syncFrom}.`);
  };

  const handleScheduleChange = async (streamName: string, schedule: string): Promise<void> => {
    const previousSchedules = streamSchedules;
    const nextSchedules = { ...streamSchedules, [streamName]: schedule };
    setStreamSchedules(nextSchedules);
    const saved = await persistStreamScheduleConfig(nextSchedules, streamSyncFrom);
    if (!saved) {
      setStreamSchedules(previousSchedules);
      return;
    }
    const match = SCHEDULE_OPTIONS.find((s) => s.value === schedule);
    toast.success(`Sync schedule for "${streamName}" set to ${match?.label ?? schedule}.`);
  };

  const handleDiscoverEntities = async (): Promise<void> => {
    onProblem(null);
    const res = await discoverMutation.mutateAsync();
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    const discoveredNames = res.value.streams.map((s) => s.name);
    if (discoveredNames.length === 0) {
      setHasDiscoveredEmpty(true);
      toast.info('No entities found.');
      return;
    }
    setHasDiscoveredEmpty(false);
    setUserSelectedStreams((prev) => Array.from(new Set([...prev, ...discoveredNames])));
    setSelectedStreams((prev) => new Set([...prev, ...discoveredNames]));
    toast.success(`Discovered ${discoveredNames.length} entity stream(s).`);
  };

  const handleCopyEntityWebhook = async (streamName: string): Promise<void> => {
    const resolvedTenantId = connection?.tenantId ?? tenantId;
    const url = buildIngressWebhookUrl(baseUrl, resolvedTenantId, connectionId, streamName);
    try {
      await navigator.clipboard.writeText(url);
      setCopiedStreamWebhook(streamName);
      toast.success(`Copied webhook URL for entity "${streamName}".`);
      setTimeout(() => {
        setCopiedStreamWebhook((curr) => (curr === streamName ? null : curr));
      }, 2000);
    } catch {
      toast.error('Unable to copy entity webhook URL to clipboard.');
    }
  };

  const handleSimulatePush = async (streamName: string): Promise<void> => {
    onProblem(null);
    const res = await simulatePushMutation.mutateAsync({
      streamName,
      count: 1,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(
      `Simulated push for "${streamName}" (${res.value.recordsPushed} record ingested into L1).`,
    );
  };

  const handleTrigger = async (
    streamName: string,
    forcedKind: typeof SyncRunKind.INCREMENTAL | typeof SyncRunKind.FULL_REFRESH,
  ): Promise<void> => {
    const trimmed = streamName.trim();
    if (!trimmed) return;
    onProblem(null);
    const res = await triggerMutation.mutateAsync({ streamName: trimmed, forcedKind });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(`Triggered sync for "${trimmed}".`);
  };

  const handleSyncAllSelected = async (): Promise<void> => {
    if (selectedStreams.size === 0) return;
    setIsSyncingAll(true);
    onProblem(null);
    let successCount = 0;
    const failedStreams: string[] = [];
    let lastProblem: ApiProblem | null = null;

    try {
      for (const streamName of selectedStreams) {
        const streamDef = catalogView.data?.streams.find((s) => s.name === streamName);
        const supportsIncremental =
          streamDef?.supportedSyncModes.includes(SyncRunKind.INCREMENTAL) ?? true;
        const forcedKind = supportsIncremental ? SyncRunKind.INCREMENTAL : SyncRunKind.FULL_REFRESH;
        const res = await triggerMutation.mutateAsync({
          streamName,
          forcedKind,
        });
        if (res.ok) {
          successCount += 1;
        } else {
          failedStreams.push(streamName);
          lastProblem = res.error;
        }
      }

      if (failedStreams.length > 0) {
        if (lastProblem) {
          onProblem(lastProblem);
        }
        toast.error(
          `Sync triggered for ${successCount} stream(s), but failed for ${failedStreams.length}: ${failedStreams.join(', ')}`,
        );
      } else {
        toast.success(`Triggered sync for ${successCount} selected entity stream(s).`);
      }
    } catch (err) {
      const problem: ApiProblem = {
        code: ApiErrorCode.SERVER_ERROR,
        status: 500,
        message:
          err instanceof Error ? err.message : 'Unexpected execution error during batch sync.',
      };
      onProblem(problem);
      toast.error(problem.message);
    } finally {
      setIsSyncingAll(false);
    }
  };

  const entityColumns = useMemo<ColumnDef<EntityRow>[]>(
    () => [
      {
        id: 'select',
        header: () => (
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-border"
            aria-label="Select all entities"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={selectedStreams.has(row.original.streamName)}
            onChange={() => toggleStream(row.original.streamName)}
            className="h-4 w-4 rounded border-border"
            aria-label={`Select ${row.original.streamName}`}
          />
        ),
      },
      {
        accessorKey: 'streamName',
        header: 'Entity',
        cell: ({ row }) => {
          const isExpanded = expandedStreams.has(row.original.streamName);
          return (
            <div className="flex items-center gap-1.5 font-mono font-semibold">
              {isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              )}
              <span>{row.original.streamName}</span>
            </div>
          );
        },
      },
      {
        id: 'syncFrom',
        header: 'Sync From',
        cell: ({ row }) => {
          const selectedValue = streamSyncFrom[row.original.streamName] ?? 'all';
          const isCustom = selectedValue === 'custom';
          return (
            <div className="flex items-center gap-2">
              <Select
                value={selectedValue}
                onValueChange={(val) => void handleSyncFromChange(row.original.streamName, val)}
              >
                <SelectTrigger className="h-7 w-32 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SYNC_FROM_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {isCustom ? (
                <Input
                  type="date"
                  value={streamCustomDates[row.original.streamName] ?? ''}
                  onChange={(e) =>
                    setStreamCustomDates((prev) => ({
                      ...prev,
                      [row.original.streamName]: e.target.value,
                    }))
                  }
                  className="h-7 w-36 text-xs px-2"
                />
              ) : null}
            </div>
          );
        },
      },
      {
        id: 'schedule',
        header: 'Schedule',
        cell: ({ row }) => (
          <Select
            value={streamSchedules[row.original.streamName] ?? '15m'}
            onValueChange={(val) => void handleScheduleChange(row.original.streamName, val)}
          >
            <SelectTrigger className="h-7 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCHEDULE_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => {
          if (
            row.original.status === EntityRowLocalStatus.UNSYNCED &&
            row.original.recordsSyncedCount === 0
          ) {
            return <span className="text-xs text-muted-foreground font-mono">—</span>;
          }
          if (row.original.status === SyncRunStatus.RUNNING) {
            return <StatusBadge label="SYNCING" tone={StatusTone.WARNING} />;
          }
          if (row.original.status === SyncRunStatus.SUCCEEDED) {
            return <StatusBadge label="SUCCEEDED" tone={StatusTone.HEALTHY} />;
          }
          if (row.original.status === SyncRunStatus.FAILED) {
            return <StatusBadge label="FAILED" tone={StatusTone.CRITICAL} />;
          }
          return <StatusBadge label={row.original.status} tone={StatusTone.NEUTRAL} />;
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isAuthPending || triggerMutation.isPending || isSyncingAll}
              onClick={() => {
                const streamDef = catalogView.data?.streams.find(
                  (s) => s.name === row.original.streamName,
                );
                const supportsIncremental =
                  streamDef?.supportedSyncModes.includes(SyncRunKind.INCREMENTAL) ?? true;
                const forcedKind = supportsIncremental
                  ? SyncRunKind.INCREMENTAL
                  : SyncRunKind.FULL_REFRESH;
                void handleTrigger(row.original.streamName, forcedKind);
              }}
              className="h-7 gap-1 text-xs"
            >
              <Play className="h-3 w-3" />
              <span>Sync</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleCopyEntityWebhook(row.original.streamName)}
              title="Copy entity-specific webhook URL"
              className="h-7 gap-1 text-xs"
            >
              {copiedStreamWebhook === row.original.streamName ? (
                <>
                  <Check className="h-3 w-3 text-emerald-600" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  <span>Webhook</span>
                </>
              )}
            </Button>
            {isSimulator ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={simulatePushMutation.isPending}
                onClick={() => void handleSimulatePush(row.original.streamName)}
                title="Emit synthetic push event into L1 Ingress"
                className="h-7 gap-1 text-xs"
              >
                <Radio className="h-3 w-3 text-primary" />
                <span>Simulate Push</span>
              </Button>
            ) : null}
            {onInspectEntity ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onInspectEntity(row.original.streamName)}
                className="h-7 gap-1 text-xs text-primary font-medium"
              >
                <Database className="h-3 w-3" />
                <span>Data</span>
              </Button>
            ) : null}
          </div>
        ),
      },
    ],
    [
      allVisibleSelected,
      selectedStreams,
      filteredEntityRows,
      streamSyncFrom,
      streamCustomDates,
      streamSchedules,
      expandedStreams,
      triggerMutation.isPending,
      simulatePushMutation.isPending,
      copiedStreamWebhook,
      isSimulator,
      isSyncingAll,
      onInspectEntity,
    ],
  );

  const runRows = useMemo(() => [...(runsView.data ?? [])], [runsView.data]);

  const runColumns = useMemo<ColumnDef<SyncRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Run ID',
        cell: ({ row }) => <CopyableIdPill value={row.original.runId} truncateLength={14} />,
      },
      {
        accessorKey: 'streamName',
        header: 'Entity',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.streamName} ({row.original.kind})
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
        accessorKey: 'recordsCount',
        header: 'Records',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.recordsCount}</span>
        ),
      },
      {
        accessorKey: 'traceId',
        header: 'Trace',
        cell: ({ row }) => <CopyableIdPill value={row.original.traceId} truncateLength={14} />,
      },
    ],
    [],
  );

  const entityTable = useReactTable({
    data: filteredEntityRows,
    columns: entityColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  const runTable = useReactTable({
    data: runRows,
    columns: runColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-4">
      {/* Header and Sync Action */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Entities</h2>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isAuthPending || discoverMutation.isPending}
            onClick={() => void handleDiscoverEntities()}
            className="h-8 gap-1.5 text-xs"
          >
            <Compass className="h-3.5 w-3.5" />
            <span>{discoverMutation.isPending ? 'Discovering...' : 'Discover Entities'}</span>
          </Button>

          <Button
            type="button"
            size="sm"
            disabled={isAuthPending || selectedStreams.size === 0 || isSyncingAll}
            onClick={() => void handleSyncAllSelected()}
            className="h-8 gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90 text-xs shadow-xs"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            <span>Sync Selected ({selectedStreams.size})</span>
          </Button>
        </div>
      </div>

      {isAuthPending ? (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
          <ShieldAlert className="h-4 w-4 shrink-0" />
          <span>Authentication Pending</span>
        </div>
      ) : null}

      {/* Entity Selection & Table Filter Controls */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {/* Single Discover Entities Search & Select */}
          <div className="w-72">
            <SearchableSelect
              value=""
              onChange={handleSelectDiscoveredEntity}
              options={availableDiscoveredOptions}
              portaled={true}
              placeholder={
                discoverMutation.isPending || catalogView.isLoading
                  ? 'Discovering Entities...'
                  : 'Discover Entities...'
              }
              disabled={isAuthPending}
              emptyText="No matching discovered entities"
            />
          </div>

          {/* Search/Filter Entities in table */}
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Entities"
              className="h-10 pl-8 text-xs font-mono rounded-xl"
            />
          </div>
        </div>

        <span className="text-xs text-muted-foreground tabular-nums">
          {selectedStreams.size} of {entityRows.length} selected
        </span>
      </div>

      {/* EDI-Style Single-Border TanStack Table with Permanent TableHeader */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <Table>
          <TableHeader className="bg-muted/50 border-b border-border">
            {entityTable.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent border-0">
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className="font-semibold text-foreground text-xs py-2.5 px-3"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {statesView.isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={entityColumns.length}
                  className="h-32 text-center text-xs text-muted-foreground"
                >
                  Loading entity streams...
                </TableCell>
              </TableRow>
            ) : filteredEntityRows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={entityColumns.length}
                  className="h-32 text-center text-xs text-muted-foreground"
                >
                  {isAuthPending
                    ? 'Authentication Pending'
                    : hasDiscoveredEmpty
                      ? 'No entities found'
                      : 'No entities'}
                </TableCell>
              </TableRow>
            ) : (
              entityTable.getRowModel().rows.map((row) => (
                <React.Fragment key={row.id}>
                  <TableRow
                    className="cursor-pointer hover:bg-muted/40 transition-colors"
                    onClick={() => toggleRowExpanded(row.original.streamName)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        className="py-2 px-3 align-middle"
                        onClick={(e) => {
                          const target = e.target as HTMLElement;
                          if (
                            target.closest(
                              'button, input, [role="combobox"], [data-radix-popper-content-wrapper]',
                            )
                          ) {
                            e.stopPropagation();
                          }
                        }}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                  {expandedStreams.has(row.original.streamName) ? (
                    <TableRow className="bg-muted/30 border-b border-border hover:bg-muted/30">
                      <TableCell colSpan={entityColumns.length} className="py-3 px-8 text-xs">
                        {(() => {
                          const streamInfo = catalogView.data?.streams.find(
                            (s) => s.name === row.original.streamName,
                          );
                          const simEntity = isSimulator
                            ? (simulatorEntitiesView.data ?? []).find(
                                (e) => e.entityName === row.original.streamName,
                              )
                            : undefined;
                          const fields =
                            streamInfo?.fields ??
                            (simEntity && isPlainRecord(simEntity.inferredJsonSchema.properties)
                              ? Object.entries(simEntity.inferredJsonSchema.properties).map(
                                  ([fieldName, rawDef]) => ({
                                    name: fieldName,
                                    dataType:
                                      isPlainRecord(rawDef) && typeof rawDef.type === 'string'
                                        ? rawDef.type
                                        : 'string',
                                    nullable: fieldName !== simEntity.primaryKeyField,
                                    description: null,
                                  }),
                                )
                              : []);
                          return (
                            <div className="space-y-2">
                              <span className="font-semibold text-foreground text-xs uppercase tracking-wider">
                                Schema Fields
                              </span>
                              {fields.length === 0 ? (
                                <span className="text-muted-foreground text-xs block">
                                  No schema fields discovered for this entity.
                                </span>
                              ) : (
                                <div className="rounded-lg border border-border bg-card overflow-hidden">
                                  <table className="w-full text-xs">
                                    <thead className="bg-muted/50 border-b border-border">
                                      <tr>
                                        <th className="text-left py-1.5 px-3 font-medium text-foreground">
                                          Field
                                        </th>
                                        <th className="text-left py-1.5 px-3 font-medium text-foreground">
                                          Type
                                        </th>
                                        <th className="text-left py-1.5 px-3 font-medium text-foreground">
                                          Nullable
                                        </th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {fields.map((f) => (
                                        <tr
                                          key={f.name}
                                          className="border-b border-border/50 last:border-0"
                                        >
                                          <td className="py-1 px-3 font-mono">{f.name}</td>
                                          <td className="py-1 px-3 font-mono text-muted-foreground">
                                            {f.dataType}
                                          </td>
                                          <td className="py-1 px-3 text-muted-foreground">
                                            {f.nullable ? 'Yes' : 'No'}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </React.Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Recent Sync Runs */}
      {runRows.length > 0 ? (
        <div className="space-y-2 pt-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Recent Sync Runs
          </span>
          <DataTable
            table={runTable}
            columnsLength={runColumns.length}
            isLoading={runsView.isLoading}
            dataLength={runRows.length}
            ariaLabel="Recent sync runs"
            emptyTitle="No Sync Runs Yet"
            onRowClick={(row) => onOpenTrace(row.original.traceId)}
          />
        </div>
      ) : null}
    </div>
  );
}

export const ConnectionStreamsSyncTab = ConnectionEntitiesSyncTab;
