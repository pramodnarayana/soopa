import {
  ApiErrorCode,
  type ApiProblem,
  Button,
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
  ChevronDown,
  ChevronRight,
  Database,
  Play,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
} from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery } from '../../application/use-catalog-queries';
import {
  useAddConnectionEntityMutation,
  useConnectionEntitiesQuery,
  useRemoveConnectionEntityMutation,
  useResetConnectionEntityCheckpointMutation,
  useUpdateConnectionEntityMutation,
} from '../../application/use-connection-entity-queries';
import {
  useDeactivateConnectionMutation,
  useDeleteConnectionMutation,
  useDiscoverCatalogMutation,
  useDiscoveredStreamsQuery,
  useRelinkConnectionMutation,
  useUpdateConnectionMutation,
} from '../../application/use-connection-queries';
import {
  useSyncRunsQuery,
  useTriggerSyncRunMutation,
} from '../../application/use-sync-run-queries';
import type { Connection } from '../../domain/connection';
import type { ConnectionEntityField } from '../../domain/connection-entity';
import {
  ConnectionStatus,
  ConnectorPropertyKey,
  EntitySyncFrom,
  type EntitySyncFromValue,
  EntitySyncSchedule,
  type EntitySyncScheduleValue,
  SyncRunKind,
  type SyncRunKindValue,
  SyncRunStatus,
} from '../../domain/enums';
import type { SyncRun } from '../../domain/sync-run';
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
} as const;

function isEntitySyncScheduleValue(value: string): value is EntitySyncScheduleValue {
  return Object.values(EntitySyncSchedule).some((item) => item === value);
}

function isEntitySyncFromValue(value: string): value is EntitySyncFromValue {
  return Object.values(EntitySyncFrom).some((item) => item === value);
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

export interface ConnectionEntitiesSyncTabProps {
  readonly connectionId: string;
  readonly connection?: Connection;
  readonly onInspectEntity?: (entityName: string) => void;
  readonly onOpenTrace: (traceId: string) => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}

const SCHEDULE_OPTIONS: readonly {
  readonly value: EntitySyncScheduleValue;
  readonly label: string;
}[] = [
  { value: EntitySyncSchedule.MANUAL, label: 'Manual' },
  { value: EntitySyncSchedule.EVERY_5M, label: 'Every 5 minutes' },
  { value: EntitySyncSchedule.EVERY_15M, label: 'Every 15 minutes' },
  { value: EntitySyncSchedule.HOURLY, label: 'Hourly' },
  { value: EntitySyncSchedule.EVERY_6H, label: 'Every 6 hours' },
  { value: EntitySyncSchedule.DAILY, label: 'Daily' },
];

const SYNC_FROM_OPTIONS: readonly {
  readonly value: EntitySyncFromValue;
  readonly label: string;
}[] = [
  { value: EntitySyncFrom.ALL, label: 'All' },
  { value: EntitySyncFrom.LAST_90D, label: 'Last 90 Days' },
  { value: EntitySyncFrom.LAST_30D, label: 'Last 30 Days' },
  { value: EntitySyncFrom.LAST_7D, label: 'Last 7 Days' },
  { value: EntitySyncFrom.LAST_24H, label: 'Last 24 Hours' },
  { value: EntitySyncFrom.CUSTOM, label: 'Specific Date' },
];

interface EntityRow {
  readonly entityId: string;
  readonly streamName: string;
  readonly syncMode: SyncRunKindValue | (string & {});
  readonly schedule: EntitySyncScheduleValue | (string & {});
  readonly syncFrom: EntitySyncFromValue | (string & {});
  readonly syncFromAt: string | null;
  readonly isEnabled: boolean;
  readonly primaryKey: readonly string[];
  readonly fields: readonly ConnectionEntityField[];
  readonly status: string;
  readonly cursorField: string | null;
  readonly cursorValue: string | null;
  readonly recordsSyncedCount: number;
  readonly lastSyncedAt: string | null;
}

export function reconcileSelectedStreamNames(
  previous: Set<string>,
  validStreamNames: ReadonlySet<string>,
  newlyAddedStreams: readonly string[] = [],
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
  const [search, setSearch] = useState('');
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [expandedStreams, setExpandedStreams] = useState<Set<string>>(new Set());

  const isAuthPending = connection?.status === ConnectionStatus.PENDING_AUTH;

  const entitiesView = useConnectionEntitiesQuery(connectionId);
  const discoveredView = useDiscoveredStreamsQuery(connectionId);
  const runsView = useSyncRunsQuery(connectionId, 40);

  const discoverMutation = useDiscoverCatalogMutation(connectionId);
  const addEntityMutation = useAddConnectionEntityMutation(connectionId);
  const updateEntityMutation = useUpdateConnectionEntityMutation(connectionId);
  const removeEntityMutation = useRemoveConnectionEntityMutation(connectionId);
  const resetCheckpointMutation = useResetConnectionEntityCheckpointMutation(connectionId);
  const triggerMutation = useTriggerSyncRunMutation(connectionId);

  useEffect(() => {
    if (entitiesView.problem) {
      onProblem(entitiesView.problem);
    }
  }, [entitiesView.problem, onProblem]);

  // Build entity rows uniformly from persisted subscribed ConnectionEntity records + latest sync runs
  const entityRows = useMemo<EntityRow[]>(() => {
    const latestRunByStream = new Map<string, SyncRun>();
    for (const run of runsView.data ?? []) {
      if (!latestRunByStream.has(run.streamName)) {
        latestRunByStream.set(run.streamName, run);
      }
    }

    return (entitiesView.data ?? []).map((entity) => {
      const latestRun = latestRunByStream.get(entity.streamName);
      const status = latestRun
        ? latestRun.status
        : entity.lastSyncedAt
          ? SyncRunStatus.SUCCEEDED
          : EntityRowLocalStatus.UNSYNCED;
      return {
        entityId: entity.entityId,
        streamName: entity.streamName,
        syncMode: entity.syncMode,
        schedule: entity.schedule,
        syncFrom: entity.syncFrom,
        syncFromAt: entity.syncFromAt,
        isEnabled: entity.isEnabled,
        primaryKey: entity.primaryKey,
        fields: entity.fields,
        status,
        cursorField: entity.cursorField,
        cursorValue: entity.cursorValue,
        recordsSyncedCount: entity.recordsSyncedCount,
        lastSyncedAt: entity.lastSyncedAt,
      };
    });
  }, [entitiesView.data, runsView.data]);

  const activeStreamNames = useMemo(() => {
    const set = new Set<string>();
    for (const row of entityRows) {
      set.add(row.streamName);
    }
    return set;
  }, [entityRows]);

  const availableDiscoveredOptions = useMemo<readonly SearchableSelectOption[]>(() => {
    const discoveredStreams = discoveredView.data?.streams ?? [];
    return discoveredStreams
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
  }, [discoveredView.data?.streams, activeStreamNames]);

  const [selectedStreams, setSelectedStreams] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const row of entityRows) {
      if (row.isEnabled) {
        initial.add(row.streamName);
      }
    }
    return initial;
  });

  const initializedEntitiesRef = React.useRef(entityRows.length > 0);
  useEffect(() => {
    if (!initializedEntitiesRef.current && (entitiesView.data?.length ?? 0) > 0) {
      initializedEntitiesRef.current = true;
      setSelectedStreams((prev) => {
        const next = new Set(prev);
        for (const entity of entitiesView.data ?? []) {
          if (entity.isEnabled) {
            next.add(entity.streamName);
          }
        }
        return next;
      });
    }
  }, [entitiesView.data]);

  useEffect(() => {
    setSelectedStreams((prev) => reconcileSelectedStreamNames(prev, activeStreamNames));
  }, [activeStreamNames]);

  const handleSelectDiscoveredEntity = useCallback(
    async (streamName: string): Promise<void> => {
      const trimmed = streamName.trim();
      if (!trimmed || activeStreamNames.has(trimmed)) return;
      onProblem(null);

      const discoveredStream = discoveredView.data?.streams.find((s) => s.name === trimmed);
      const supportsIncremental =
        discoveredStream === undefined ||
        discoveredStream.supportedSyncModes.length === 0 ||
        discoveredStream.supportedSyncModes.includes(SyncRunKind.INCREMENTAL);
      const syncMode = supportsIncremental ? SyncRunKind.INCREMENTAL : SyncRunKind.FULL_REFRESH;

      const res = await addEntityMutation.mutateAsync({
        streamName: trimmed,
        syncMode,
        schedule: EntitySyncSchedule.MANUAL,
        syncFrom: EntitySyncFrom.ALL,
        isEnabled: true,
        primaryKey: discoveredStream?.primaryKey ?? [],
        fields: discoveredStream?.fields ?? [],
        cursorField: discoveredStream?.cursorField ?? null,
        defaultTransformationId: discoveredStream?.defaultTransformationId ?? null,
        defaultTransformationVersion: discoveredStream?.defaultTransformationVersion ?? 1,
      });
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      setSelectedStreams((prev) => new Set([...prev, res.value.streamName]));
      toast.success(`Subscribed to "${res.value.streamName}".`);
    },
    [activeStreamNames, discoveredView.data?.streams, addEntityMutation, onProblem],
  );

  const filteredEntityRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entityRows;
    return entityRows.filter((r) => r.streamName.toLowerCase().includes(q));
  }, [entityRows, search]);

  const allVisibleSelected =
    filteredEntityRows.length > 0 &&
    filteredEntityRows.every((r) => selectedStreams.has(r.streamName));

  const toggleSelectAll = useCallback(() => {
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
  }, [allVisibleSelected, filteredEntityRows, selectedStreams]);

  const toggleStream = useCallback((streamName: string) => {
    setSelectedStreams((prev) => {
      const next = new Set(prev);
      if (next.has(streamName)) {
        next.delete(streamName);
      } else {
        next.add(streamName);
      }
      return next;
    });
  }, []);

  const toggleRowExpanded = useCallback((streamName: string) => {
    setExpandedStreams((prev) => {
      const next = new Set(prev);
      if (next.has(streamName)) {
        next.delete(streamName);
      } else {
        next.add(streamName);
      }
      return next;
    });
  }, []);

  const handleSyncFromChange = useCallback(
    async (row: EntityRow, rawSyncFrom: string): Promise<void> => {
      if (!isEntitySyncFromValue(rawSyncFrom)) return;
      onProblem(null);
      const fallbackDateIso = `${new Date().toISOString().slice(0, 10)}T00:00:00Z`;
      const syncFromAt =
        rawSyncFrom === EntitySyncFrom.CUSTOM ? (row.syncFromAt ?? fallbackDateIso) : null;

      const res = await updateEntityMutation.mutateAsync({
        streamName: row.streamName,
        input: {
          syncFrom: rawSyncFrom,
          syncFromAt,
        },
      });
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      const match = SYNC_FROM_OPTIONS.find((opt) => opt.value === rawSyncFrom);
      toast.success(`Sync from for "${row.streamName}" set to ${match?.label ?? rawSyncFrom}.`);
    },
    [updateEntityMutation, onProblem],
  );

  const handleCustomDateChange = useCallback(
    async (streamName: string, nextDate: string): Promise<void> => {
      if (!nextDate) return;
      onProblem(null);
      const res = await updateEntityMutation.mutateAsync({
        streamName,
        input: {
          syncFrom: EntitySyncFrom.CUSTOM,
          syncFromAt: `${nextDate}T00:00:00Z`,
        },
      });
      if (!res.ok) {
        onProblem(res.error);
      }
    },
    [updateEntityMutation, onProblem],
  );

  const handleScheduleChange = useCallback(
    async (streamName: string, rawSchedule: string): Promise<void> => {
      if (!isEntitySyncScheduleValue(rawSchedule)) return;
      onProblem(null);
      const res = await updateEntityMutation.mutateAsync({
        streamName,
        input: { schedule: rawSchedule },
      });
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      const match = SCHEDULE_OPTIONS.find((opt) => opt.value === rawSchedule);
      toast.success(`Sync schedule for "${streamName}" set to ${match?.label ?? rawSchedule}.`);
    },
    [updateEntityMutation, onProblem],
  );

  const handleRemoveEntity = useCallback(
    async (streamName: string): Promise<void> => {
      onProblem(null);
      const res = await removeEntityMutation.mutateAsync(streamName);
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      toast.success(`Removed "${streamName}" from subscribed entities.`);
    },
    [removeEntityMutation, onProblem],
  );

  const handleResetCheckpoint = useCallback(
    async (streamName: string): Promise<void> => {
      onProblem(null);
      const res = await resetCheckpointMutation.mutateAsync(streamName);
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      toast.success(`Reset sync checkpoint for "${streamName}".`);
    },
    [resetCheckpointMutation, onProblem],
  );

  const handleDiscoverDropdownOpenChange = (open: boolean): void => {
    if (!open || isAuthPending || discoverMutation.isPending) {
      return;
    }
    onProblem(null);
    void discoverMutation.mutateAsync().then((res) => {
      if (!res.ok) {
        onProblem(res.error);
      }
    });
  };

  const handleTrigger = useCallback(
    async (streamName: string, forcedKind: SyncRunKindValue): Promise<void> => {
      const trimmed = streamName.trim();
      if (!trimmed) return;
      onProblem(null);
      const res = await triggerMutation.mutateAsync({ streamName: trimmed, forcedKind });
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      toast.success(`Triggered sync for "${trimmed}".`);
    },
    [triggerMutation, onProblem],
  );

  const handleSyncAllSelected = async (): Promise<void> => {
    if (selectedStreams.size === 0) return;
    setIsSyncingAll(true);
    onProblem(null);
    let successCount = 0;
    const failedStreams: string[] = [];
    let lastProblem: ApiProblem | null = null;

    try {
      for (const streamName of selectedStreams) {
        const entityRow = entityRows.find((r) => r.streamName === streamName);
        const forcedKind =
          entityRow?.syncMode === SyncRunKind.FULL_REFRESH
            ? SyncRunKind.FULL_REFRESH
            : SyncRunKind.INCREMENTAL;
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
          const selectedValue = row.original.syncFrom;
          const selectedLabel =
            SYNC_FROM_OPTIONS.find((opt) => opt.value === selectedValue)?.label ?? selectedValue;
          const isCustom = selectedValue === EntitySyncFrom.CUSTOM;
          const customDateValue = row.original.syncFromAt
            ? row.original.syncFromAt.slice(0, 10)
            : '';
          return (
            <div className="flex items-center gap-2">
              <Select
                value={selectedValue}
                onValueChange={(val) => void handleSyncFromChange(row.original, val)}
              >
                <SelectTrigger className="h-7 w-32 text-xs">
                  <SelectValue>{selectedLabel}</SelectValue>
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
                  value={customDateValue}
                  onChange={(e) =>
                    void handleCustomDateChange(row.original.streamName, e.target.value)
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
        cell: ({ row }) => {
          const selectedScheduleLabel =
            SCHEDULE_OPTIONS.find((opt) => opt.value === row.original.schedule)?.label ??
            row.original.schedule;
          return (
            <Select
              value={row.original.schedule}
              onValueChange={(val) => void handleScheduleChange(row.original.streamName, val)}
            >
              <SelectTrigger className="h-7 w-36 text-xs">
                <SelectValue>{selectedScheduleLabel}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {SCHEDULE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        },
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
        cell: ({ row }) => {
          const forcedKind =
            row.original.syncMode === SyncRunKind.FULL_REFRESH
              ? SyncRunKind.FULL_REFRESH
              : SyncRunKind.INCREMENTAL;
          const canResetCheckpoint =
            row.original.recordsSyncedCount > 0 || row.original.cursorValue !== null;
          return (
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isAuthPending || triggerMutation.isPending || isSyncingAll}
                onClick={() => void handleTrigger(row.original.streamName, forcedKind)}
                className="h-7 gap-1 text-xs"
              >
                <Play className="h-3 w-3" />
                <span>Sync</span>
              </Button>
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
              {canResetCheckpoint ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={
                    resetCheckpointMutation.isPending &&
                    resetCheckpointMutation.variables === row.original.streamName
                  }
                  onClick={() => void handleResetCheckpoint(row.original.streamName)}
                  className="h-7 gap-1 text-xs text-muted-foreground hover:text-foreground"
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>Reset</span>
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove ${row.original.streamName}`}
                disabled={
                  removeEntityMutation.isPending &&
                  removeEntityMutation.variables === row.original.streamName
                }
                onClick={() => void handleRemoveEntity(row.original.streamName)}
                className="h-7 px-2 text-xs text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          );
        },
      },
    ],
    [
      allVisibleSelected,
      selectedStreams,
      expandedStreams,
      isAuthPending,
      triggerMutation.isPending,
      resetCheckpointMutation.isPending,
      resetCheckpointMutation.variables,
      removeEntityMutation.isPending,
      removeEntityMutation.variables,
      isSyncingAll,
      onInspectEntity,
      toggleSelectAll,
      toggleStream,
      handleSyncFromChange,
      handleCustomDateChange,
      handleScheduleChange,
      handleTrigger,
      handleResetCheckpoint,
      handleRemoveEntity,
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
          {/* Single Stateless Live Discover Entities Combobox */}
          <div className="w-72">
            <SearchableSelect
              value=""
              onChange={(streamName) => void handleSelectDiscoveredEntity(streamName)}
              onOpenChange={handleDiscoverDropdownOpenChange}
              options={availableDiscoveredOptions}
              portaled={true}
              placeholder="Discover Entities..."
              searchPlaceholder="Search entities..."
              loading={discoverMutation.isPending || addEntityMutation.isPending}
              loadingText="Discovering entities..."
              disabled={isAuthPending}
              emptyText={
                (discoveredView.data?.streams.length ?? 0) > 0
                  ? 'All discovered entities added'
                  : 'No entities found'
              }
            />
          </div>

          {/* Search/Filter Subscribed Entities in table */}
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

      {/* Subscribed Entities Control Plane Table */}
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
            {entitiesView.isLoading ? (
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
                  {isAuthPending ? 'Authentication Pending' : 'No entities'}
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
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-semibold text-foreground text-xs uppercase tracking-wider">
                              Schema Fields
                            </span>
                            {row.original.primaryKey.length > 0 ? (
                              <span className="font-mono text-xs text-muted-foreground">
                                Primary Key: {row.original.primaryKey.join(', ')}
                              </span>
                            ) : null}
                          </div>
                          {row.original.fields.length === 0 ? (
                            <span className="text-muted-foreground text-xs block">
                              No schema fields recorded for this entity.
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
                                  {row.original.fields.map((f) => (
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
