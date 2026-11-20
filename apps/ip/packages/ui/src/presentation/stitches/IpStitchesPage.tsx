import {
  Button,
  CopyableIdPill,
  DataTable,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  GitFork,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Workflow,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useStitchDefinitionsQuery,
  useStitchesQuery,
  useStitchRunsQuery,
  useToggleStitchStateMutation,
} from '../../application/use-stitch-queries';
import type { Stitch, StitchDefinition, StitchRun } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import {
  DeleteStitchModal,
  DispatchCanonicalEventModal,
  EditStitchModal,
  RegisterStitchModal,
} from './StitchModals';

export function ActiveStitchesTable({
  stitches,
  isLoading,
  onOpenDefinition,
  onEditStitch,
  onDeleteStitch,
  onToggleState,
  onDispatchEvent,
}: {
  readonly stitches: readonly Stitch[];
  readonly isLoading: boolean;
  readonly onOpenDefinition: (workflowId: string) => void;
  readonly onEditStitch: (stitch: Stitch) => void;
  readonly onDeleteStitch: (stitch: Stitch) => void;
  readonly onToggleState: (stitch: Stitch) => void;
  readonly onDispatchEvent: (stitch: Stitch) => void;
}) {
  const rows = useMemo(() => [...stitches], [stitches]);
  const columns = useMemo<ColumnDef<Stitch>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Stitch Pipeline',
        cell: ({ row }) => {
          const displayName = row.original.name?.trim() || row.original.workflowId;
          const hasCustomName = Boolean(row.original.name?.trim());
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-semibold text-xs text-foreground">{displayName}</span>
              {hasCustomName ? (
                <span className="font-mono text-[11px] text-muted-foreground">
                  {row.original.workflowId} (v{row.original.workflowVersion})
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: 'canonicalEventType',
        header: 'L3 Canonical Event',
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.canonicalEventType}</span>
        ),
      },
      {
        accessorKey: 'mappingSpecId',
        header: 'Mapping Spec',
        cell: ({ row }) =>
          row.original.mappingSpecId ? (
            <CopyableIdPill value={row.original.mappingSpecId} />
          ) : (
            <span className="text-muted-foreground text-xs">—</span>
          ),
      },
      {
        accessorKey: 'workflowId',
        header: 'Target Stitch DAG',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.workflowId} (v{row.original.workflowVersion})
          </span>
        ),
      },
      {
        accessorKey: 'isTrigger',
        header: 'Role',
        cell: ({ row }) => (
          <StatusBadge
            label={
              row.original.isTrigger
                ? 'DAG Trigger'
                : `Gate: ${row.original.conditionEventKey ?? 'wait'}`
            }
            tone={row.original.isTrigger ? StatusTone.HEALTHY : StatusTone.WARNING}
          />
        ),
      },
      {
        accessorKey: 'idempotencyKeyField',
        header: 'Idempotency · Concurrency',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.idempotencyKeyField} · {row.original.concurrencyKeyField ?? 'unbounded'}
          </span>
        ),
      },
      {
        accessorKey: 'isActive',
        header: 'State',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.isActive ? 'ACTIVE' : 'PAUSED'}
            tone={row.original.isActive ? StatusTone.HEALTHY : StatusTone.NEUTRAL}
          />
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => {
          const stitch = row.original;
          return (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                title={stitch.isActive ? 'Pause pipeline' : 'Activate pipeline'}
                onClick={() => onToggleState(stitch)}
              >
                {stitch.isActive ? (
                  <Pause className="h-3.5 w-3.5 text-amber-500" />
                ) : (
                  <Play className="h-3.5 w-3.5 text-emerald-500" />
                )}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0"
                    aria-label="Stitch actions"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="text-xs">
                  <DropdownMenuItem
                    onClick={() => onEditStitch(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>Edit Pipeline</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onToggleState(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    {stitch.isActive ? (
                      <>
                        <Pause className="h-3.5 w-3.5 text-amber-500" />
                        <span>Pause Pipeline</span>
                      </>
                    ) : (
                      <>
                        <Play className="h-3.5 w-3.5 text-emerald-500" />
                        <span>Activate Pipeline</span>
                      </>
                    )}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onDispatchEvent(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    <Send className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>Dispatch Test Event</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => onDeleteStitch(stitch)}
                    className="gap-2 text-destructive focus:text-destructive cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>Delete Pipeline</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    [onDeleteStitch, onDispatchEvent, onEditStitch, onToggleState],
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
      ariaLabel="Active L4 Stitches"
      emptyIcon={<Workflow className="h-6 w-6" />}
      emptyTitle="No Active Stitches Configured"
      emptyDescription="Stitches route normalized CIM entities to target destinations (like Kafka or ERP). Click Register Stitch or Stitch & Field Mapper to create and activate a pipeline."
      onRowClick={(row) => onOpenDefinition(row.original.workflowId)}
    />
  );
}

function StitchDefinitionsTable({
  definitions,
  isLoading,
  onOpenDefinition,
}: {
  readonly definitions: readonly StitchDefinition[];
  readonly isLoading: boolean;
  readonly onOpenDefinition: (workflowId: string) => void;
}) {
  const rows = useMemo(() => [...definitions], [definitions]);
  const columns = useMemo<ColumnDef<StitchDefinition>[]>(
    () => [
      {
        accessorKey: 'workflowId',
        header: 'Workflow ID',
        cell: ({ row }) => (
          <span className="font-mono font-semibold">{row.original.workflowId}</span>
        ),
      },
      {
        accessorKey: 'version',
        header: 'Version',
        cell: ({ row }) => <span className="font-mono text-xs">v{row.original.version}</span>,
      },
      {
        accessorKey: 'defaultPriority',
        header: 'Default Priority',
        cell: ({ row }) => (
          <StatusBadge label={row.original.defaultPriority} tone={StatusTone.NEUTRAL} />
        ),
      },
      {
        id: 'nodeCount',
        header: 'DAG Nodes',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.nodes.length} nodes</span>
        ),
      },
      {
        accessorKey: 'description',
        header: 'Description',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">{row.original.description}</span>
        ),
      },
    ],
    [],
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
      ariaLabel="Registered Stitch workflow DAG definitions"
      emptyIcon={<GitFork className="h-6 w-6" />}
      emptyTitle="No Workflow DAG Definitions Found"
      onRowClick={(row) => onOpenDefinition(row.original.workflowId)}
    />
  );
}

function StitchRunsTable({
  runs,
  isLoading,
  onOpenRun,
}: {
  readonly runs: readonly StitchRun[];
  readonly isLoading: boolean;
  readonly onOpenRun: (runId: string) => void;
}) {
  const rows = useMemo(() => [...runs], [runs]);
  const columns = useMemo<ColumnDef<StitchRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Run ID',
        cell: ({ row }) => <CopyableIdPill value={row.original.runId} truncateLength={18} />,
      },
      {
        accessorKey: 'workflowId',
        header: 'Workflow DAG',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.workflowId} (v{row.original.workflowVersion})
          </span>
        ),
      },
      {
        accessorKey: 'correlationId',
        header: 'Correlation',
        cell: ({ row }) =>
          row.original.correlationId ? (
            <CopyableIdPill value={row.original.correlationId} />
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapStitchRunStatusTone(row.original.status)}
          />
        ),
      },
      {
        id: 'steps',
        header: 'Steps',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.steps.length}</span>
        ),
      },
      {
        accessorKey: 'createdAt',
        header: 'Started',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatRelativeTimestamp(row.original.createdAt)}
          </span>
        ),
      },
    ],
    [],
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
      ariaLabel="Durable Stitch execution runs"
      emptyIcon={<Workflow className="h-6 w-6" />}
      emptyTitle="No Durable Stitch Runs Found"
      emptyDescription="Dispatch a canonical event or ingest live connector traffic to execute durable DAG runs."
      onRowClick={(row) => onOpenRun(row.original.runId)}
    />
  );
}

export function IpStitchesPage() {
  const { navigation } = useIpWorkspace();
  const [registerOpen, setRegisterOpen] = useState(false);
  const [editStitch, setEditStitch] = useState<Stitch | null>(null);
  const [deleteStitch, setDeleteStitch] = useState<Stitch | null>(null);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatchCanonicalEventType, setDispatchCanonicalEventType] = useState<string | undefined>(
    undefined,
  );

  const stitchesView = useStitchesQuery();
  const defsView = useStitchDefinitionsQuery();
  const runsView = useStitchRunsQuery({ limit: 50 });
  const toggleMutation = useToggleStitchStateMutation();

  const combinedProblem = stitchesView.problem ?? defsView.problem ?? runsView.problem;

  const handleToggleState = async (stitch: Stitch): Promise<void> => {
    const nextState = !stitch.isActive;
    const res = await toggleMutation.mutateAsync({
      stitchId: stitch.id,
      isActive: nextState,
    });
    if (res.ok) {
      toast.success(
        nextState
          ? `Activated Stitch '${stitch.name || stitch.workflowId}'.`
          : `Paused Stitch '${stitch.name || stitch.workflowId}'.`,
      );
    } else {
      toast.error(res.error.message || 'Failed to update stitch state.');
    }
  };

  const handleOpenDispatchForStitch = (stitch: Stitch): void => {
    setDispatchCanonicalEventType(stitch.canonicalEventType);
    setDispatchOpen(true);
  };

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="L4 Durable Orchestration"
        title="Stitches & Topological DAG Runs"
        subtitle="Route normalized domain entities to target destinations (Kafka, ERP, Webhooks) and monitor live step execution."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setDispatchCanonicalEventType(undefined);
                setDispatchOpen(true);
              }}
              className="gap-1.5"
            >
              <Send className="h-3.5 w-3.5" />
              <span>Test Event Dispatch</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRegisterOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>Register Stitch</span>
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                if (navigation.toStitchMapper) {
                  navigation.toStitchMapper();
                }
              }}
              className="gap-1.5"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Stitch & Field Mapper</span>
            </Button>
          </>
        }
      />

      <ApiProblemBanner problem={combinedProblem} />

      <Tabs defaultValue="runs">
        <TabsList>
          <TabsTrigger value="runs">
            Durable Stitch Runs ({(runsView.data ?? []).length})
          </TabsTrigger>
          <TabsTrigger value="stitches">
            Active Stitches ({(stitchesView.data ?? []).length})
          </TabsTrigger>
          <TabsTrigger value="definitions">
            Workflow DAGs ({(defsView.data ?? []).length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="runs" className="pt-4">
          <StitchRunsTable
            runs={runsView.data ?? []}
            isLoading={runsView.isLoading}
            onOpenRun={(runId) => navigation.toStitchRun(runId)}
          />
        </TabsContent>

        <TabsContent value="stitches" className="pt-4">
          <ActiveStitchesTable
            stitches={stitchesView.data ?? []}
            isLoading={stitchesView.isLoading}
            onOpenDefinition={(wfId) => navigation.toStitchDefinition(wfId)}
            onEditStitch={(s) => setEditStitch(s)}
            onDeleteStitch={(s) => setDeleteStitch(s)}
            onToggleState={(s) => void handleToggleState(s)}
            onDispatchEvent={handleOpenDispatchForStitch}
          />
        </TabsContent>

        <TabsContent value="definitions" className="pt-4">
          <StitchDefinitionsTable
            definitions={defsView.data ?? []}
            isLoading={defsView.isLoading}
            onOpenDefinition={(wfId) => navigation.toStitchDefinition(wfId)}
          />
        </TabsContent>
      </Tabs>

      <RegisterStitchModal
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        definitions={defsView.data ?? []}
      />

      <EditStitchModal
        open={Boolean(editStitch)}
        onOpenChange={(open) => {
          if (!open) setEditStitch(null);
        }}
        stitch={editStitch}
      />

      <DeleteStitchModal
        open={Boolean(deleteStitch)}
        onOpenChange={(open) => {
          if (!open) setDeleteStitch(null);
        }}
        stitch={deleteStitch}
      />

      <DispatchCanonicalEventModal
        open={dispatchOpen}
        onOpenChange={setDispatchOpen}
        onOpenRun={(runId) => navigation.toStitchRun(runId)}
        defaultCanonicalEventType={dispatchCanonicalEventType}
      />
    </div>
  );
}
