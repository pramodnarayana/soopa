import {
  Button,
  CopyableIdPill,
  DataTable,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { GitFork, Plus, Send, Workflow } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import {
  useStitchDefinitionsQuery,
  useStitchesQuery,
  useStitchRunsQuery,
} from '../../application/use-stitch-queries';
import type { Stitch, StitchDefinition, StitchRun } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import { DispatchCanonicalEventModal, RegisterStitchModal } from './StitchModals';

function ActiveStitchesTable({
  stitches,
  isLoading,
  onOpenDefinition,
}: {
  readonly stitches: readonly Stitch[];
  readonly isLoading: boolean;
  readonly onOpenDefinition: (workflowId: string) => void;
}) {
  const rows = useMemo(() => [...stitches], [stitches]);
  const columns = useMemo<ColumnDef<Stitch>[]>(
    () => [
      {
        accessorKey: 'canonicalEventType',
        header: 'L3 Canonical Event',
        cell: ({ row }) => (
          <span className="font-mono font-semibold">{row.original.canonicalEventType}</span>
        ),
      },
      {
        accessorKey: 'workflowId',
        header: 'Target Stitch DAG',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
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
      ariaLabel="Active L4 Stitches"
      emptyIcon={<Workflow className="h-6 w-6" />}
      emptyTitle="No Stitches Registered"
      emptyDescription="Click Register Stitch to bind an L3 Canonical Event Type to a durable DAG definition."
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
  const [dispatchOpen, setDispatchOpen] = useState(false);

  const stitchesView = useStitchesQuery();
  const defsView = useStitchDefinitionsQuery();
  const runsView = useStitchRunsQuery({ limit: 50 });

  const combinedProblem = stitchesView.problem ?? defsView.problem ?? runsView.problem;

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="L4 Durable Orchestration"
        title="Stitches & Topological DAG Runs"
        subtitle="Inspect code-first durable DAG topologies, bind canonical event triggers & WAIT_FOR_EVENT gates, and monitor live step execution."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setDispatchOpen(true)}
              className="gap-1.5"
            >
              <Send className="h-3.5 w-3.5" />
              <span>Test Event Dispatch</span>
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => setRegisterOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              <span>Register Stitch</span>
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

      <DispatchCanonicalEventModal
        open={dispatchOpen}
        onOpenChange={setDispatchOpen}
        onOpenRun={(runId) => navigation.toStitchRun(runId)}
      />
    </div>
  );
}
