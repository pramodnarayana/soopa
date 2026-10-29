import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  DataTable,
  Input,
  ReplayBadge,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Cable,
  CheckCircle2,
  GitMerge,
  Search,
  Workflow,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import { useStitchesQuery, useStitchRunsQuery } from '../../application/use-stitch-queries';
import { useRecentTracesQuery } from '../../application/use-trace-queries';
import type { Connection } from '../../domain/connection';
import { ConnectionStatus, StitchRunStatus, TraceStatus } from '../../domain/enums';
import type { StitchRun } from '../../domain/stitch';
import type { IpTraceLineageItem } from '../../domain/trace';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { LayerTagBadge } from '../shared/FiveLayerStagePill';
import { IpPageHeader } from '../shared/IpPageHeader';
import {
  formatRelativeTimestamp,
  mapConnectionStatusTone,
  mapStitchRunStatusTone,
  mapTraceStatusTone,
} from '../shared/status-mapping';

const PIPELINE_STEPS: ReadonlyArray<{
  readonly code: string;
  readonly name: string;
  readonly summary: string;
}> = [
  { code: 'L1', name: 'Wire Ingest', summary: 'Immutable raw HTTP/Webhook/Pull capture & SHA-256' },
  {
    code: 'L2',
    name: 'Universal Replica',
    summary: 'Deduplicated per-stream records & generation tracking',
  },
  {
    code: 'L3',
    name: 'Canonical + GEM',
    summary: 'Typed entities, extensions & Rosetta cross-references',
  },
  {
    code: 'L4',
    name: 'Durable Stitch',
    summary: 'Topological DAG, wait gates & rate-safe retries',
  },
  {
    code: 'L5',
    name: 'Outbound Wire',
    summary: 'Idempotent destination writes & Retry-After audit',
  },
];

function computeAttentionConnections(connections: readonly Connection[]): readonly Connection[] {
  return connections.filter(
    (conn) =>
      conn.status === ConnectionStatus.AUTH_EXPIRED ||
      conn.status === ConnectionStatus.DISCONNECTED ||
      conn.status === ConnectionStatus.SUSPENDED,
  );
}

function countHealthyTraces(traces: readonly IpTraceLineageItem[]): number {
  return traces.filter(
    (item) => item.status === TraceStatus.DELIVERED || item.status === TraceStatus.NORMALIZED,
  ).length;
}

function countInFlightRuns(runs: readonly StitchRun[]): number {
  return runs.filter(
    (run) =>
      run.status === StitchRunStatus.RUNNING ||
      run.status === StitchRunStatus.WAITING ||
      run.status === StitchRunStatus.PENDING,
  ).length;
}

function HeroCorrelationBar({
  onSubmitCorrelation,
}: {
  readonly onSubmitCorrelation: (query: string) => void;
}) {
  const [value, setValue] = useState('');

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    onSubmitCorrelation(trimmed);
  };

  return (
    <Card className="border-primary/40 bg-accent/60">
      <CardContent className="pt-4">
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-3 left-3.5 h-4 w-4 text-brand-ink" />
            <Input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label="Search business correlation key or trace ID"
              placeholder="Instant <15ms Support Audit — enter meter_id (MTR-700), order_id, external record ID, or ip_trc_..."
              className="h-11 bg-card pl-10 font-mono text-sm"
            />
          </div>
          <Button type="submit" size="cta" className="gap-2">
            <span>Inspect Lineage</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function KpiPostureStrip({
  activeConnections,
  totalConnections,
  healthyTraces,
  totalTraces,
  activeStitches,
  inFlightRuns,
}: {
  readonly activeConnections: number;
  readonly totalConnections: number;
  readonly healthyTraces: number;
  readonly totalTraces: number;
  readonly activeStitches: number;
  readonly inFlightRuns: number;
}) {
  return (
    <section
      aria-label="Operational posture KPIs"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      <Card>
        <CardHeader>
          <CardDescription className="flex items-center justify-between">
            <span>Active Connections</span>
            <Cable className="h-4 w-4 text-brand-ink" />
          </CardDescription>
          <CardTitle className="font-mono text-2xl font-bold tabular-nums">
            {activeConnections} / {totalConnections}
          </CardTitle>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription className="flex items-center justify-between">
            <span>Recent Trace Health</span>
            <CheckCircle2 className="h-4 w-4 text-status-healthy-fg" />
          </CardDescription>
          <CardTitle className="font-mono text-2xl font-bold tabular-nums">
            {healthyTraces} / {totalTraces}
          </CardTitle>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription className="flex items-center justify-between">
            <span>Active L4 Stitches</span>
            <GitMerge className="h-4 w-4 text-brand-ink" />
          </CardDescription>
          <CardTitle className="font-mono text-2xl font-bold tabular-nums">
            {activeStitches}
          </CardTitle>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription className="flex items-center justify-between">
            <span>In-Flight Durable Runs</span>
            <Workflow className="h-4 w-4 text-brand-ink" />
          </CardDescription>
          <CardTitle className="font-mono text-2xl font-bold tabular-nums">
            {inFlightRuns}
          </CardTitle>
        </CardHeader>
      </Card>
    </section>
  );
}

function ConnectionAttentionRadar({
  items,
  onSelectConnection,
}: {
  readonly items: readonly Connection[];
  readonly onSelectConnection: (connectionId: string) => void;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <Card className="border-status-warning-border bg-status-warning-bg/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-status-warning-fg">
          <AlertTriangle className="h-4 w-4" />
          <span>Connection Attention Radar ({items.length})</span>
        </CardTitle>
        <CardDescription>
          Credentials or OAuth2 tokens requiring re-linking to restore uninterrupted pull/delivery
          flows.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
        {items.map((conn) => (
          <div
            key={conn.id}
            className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3"
          >
            <div className="min-w-0 space-y-0.5">
              <div className="truncate font-semibold text-foreground">{conn.name}</div>
              <div className="truncate text-xs text-muted-foreground">
                {conn.appId} · {conn.lastErrorMessage ?? 'Credentials require refresh'}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge label={conn.status} tone={mapConnectionStatusTone(conn.status)} />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onSelectConnection(conn.id)}
              >
                Re-Link
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RecentTracesCard({
  traces,
  isLoading,
  onOpenTrace,
  onViewAll,
}: {
  readonly traces: readonly IpTraceLineageItem[];
  readonly isLoading: boolean;
  readonly onOpenTrace: (traceId: string) => void;
  readonly onViewAll: () => void;
}) {
  const columns = useMemo<ColumnDef<IpTraceLineageItem>[]>(
    () => [
      {
        accessorKey: 'traceId',
        header: 'Trace ID',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <CopyableIdPill value={row.original.traceId} truncateLength={18} />
            <ReplayBadge count={row.original.replayCount} />
          </div>
        ),
      },
      {
        accessorKey: 'correlationId',
        header: 'Correlation Key',
        cell: ({ row }) =>
          row.original.correlationId ? (
            <CopyableIdPill value={row.original.correlationId} />
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        accessorKey: 'primaryLayer',
        header: 'Furthest Stage',
        cell: ({ row }) => <LayerTagBadge layer={row.original.primaryLayer} />,
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge label={row.original.status} tone={mapTraceStatusTone(row.original.status)} />
        ),
      },
      {
        accessorKey: 'createdAt',
        header: 'Observed',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatRelativeTimestamp(row.original.createdAt)}
          </span>
        ),
      },
    ],
    [],
  );

  const data = useMemo(() => [...traces], [traces]);
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Recent 5-Layer Support Traces</CardTitle>
          <CardDescription>
            Click any trace to inspect L1→L5 wire & canonical payloads.
          </CardDescription>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onViewAll}>
          View Timeline
        </Button>
      </CardHeader>
      <CardContent>
        <DataTable
          table={table}
          columnsLength={columns.length}
          isLoading={isLoading}
          dataLength={data.length}
          ariaLabel="Recent support traces"
          emptyIcon={<Activity className="h-6 w-6" />}
          emptyTitle="No Traces Recorded Yet"
          emptyDescription="Ingest a webhook or trigger a pull sync to populate the 5-layer audit ledger."
          onRowClick={(row) => onOpenTrace(row.original.traceId)}
        />
      </CardContent>
    </Card>
  );
}

function RecentStitchRunsCard({
  runs,
  isLoading,
  onOpenRun,
  onViewAll,
}: {
  readonly runs: readonly StitchRun[];
  readonly isLoading: boolean;
  readonly onOpenRun: (runId: string) => void;
  readonly onViewAll: () => void;
}) {
  const columns = useMemo<ColumnDef<StitchRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Run ID',
        cell: ({ row }) => <CopyableIdPill value={row.original.runId} truncateLength={16} />,
      },
      {
        accessorKey: 'workflowId',
        header: 'Stitch Workflow',
        cell: ({ row }) => (
          <span className="font-mono text-xs font-medium">
            {row.original.workflowId} (v{row.original.workflowVersion})
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'State',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapStitchRunStatusTone(row.original.status)}
          />
        ),
      },
      {
        accessorKey: 'priority',
        header: 'Priority',
        cell: ({ row }) => <StatusBadge label={row.original.priority} tone={StatusTone.NEUTRAL} />,
      },
    ],
    [],
  );

  const data = useMemo(() => [...runs], [runs]);
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Recent Durable Stitch Runs</CardTitle>
          <CardDescription>Live DAG execution runs across L4 orchestration shards.</CardDescription>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onViewAll}>
          Open Stitches
        </Button>
      </CardHeader>
      <CardContent>
        <DataTable
          table={table}
          columnsLength={columns.length}
          isLoading={isLoading}
          dataLength={data.length}
          ariaLabel="Recent durable stitch runs"
          emptyIcon={<Workflow className="h-6 w-6" />}
          emptyTitle="No Durable Stitch Runs Yet"
          emptyDescription="Register a Stitch and dispatch a canonical L3 event to execute a durable DAG."
          onRowClick={(row) => onOpenRun(row.original.runId)}
        />
      </CardContent>
    </Card>
  );
}

export function IpCommandCenterPage() {
  const { navigation } = useIpWorkspace();
  const connectionsView = useConnectionsQuery();
  const tracesView = useRecentTracesQuery({ limit: 10 });
  const stitchesView = useStitchesQuery();
  const runsView = useStitchRunsQuery({ limit: 8 });

  const connections = connectionsView.data ?? [];
  const traces = tracesView.data ?? [];
  const stitches = stitchesView.data ?? [];
  const runs = runsView.data ?? [];

  const activeConnections = connections.filter((c) => c.status === ConnectionStatus.ACTIVE).length;
  const attentionConnections = computeAttentionConnections(connections);

  const handleCorrelationJump = (query: string): void => {
    if (query.startsWith('ip_trc_')) {
      navigation.toTraceDetail(query);
      return;
    }
    navigation.toTraces(query);
  };

  const firstProblem =
    connectionsView.problem ?? tracesView.problem ?? stitchesView.problem ?? runsView.problem;

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Operational Glass Box"
        title="Integration Platform Command Center"
        subtitle="Audit every wire payload, canonical entity, GlobalEntityMap cross-reference, and durable Stitch step in under 15ms."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => navigation.toConnections()}
            >
              Manage Connections
            </Button>
            <Button type="button" size="sm" onClick={() => navigation.toTransformations()}>
              Shadow Workbench
            </Button>
          </>
        }
      />

      <ApiProblemBanner problem={firstProblem} />

      <HeroCorrelationBar onSubmitCorrelation={handleCorrelationJump} />

      <KpiPostureStrip
        activeConnections={activeConnections}
        totalConnections={connections.length}
        healthyTraces={countHealthyTraces(traces)}
        totalTraces={traces.length}
        activeStitches={stitches.filter((s) => s.isActive).length}
        inFlightRuns={countInFlightRuns(runs)}
      />

      <section
        aria-label="5-Layer Integration Architecture"
        className="grid grid-cols-1 gap-3 md:grid-cols-5"
      >
        {PIPELINE_STEPS.map((step) => (
          <div key={step.code} className="rounded-xl border border-border bg-card p-3.5 shadow-2xs">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-8 items-center justify-center rounded-md bg-primary font-mono text-xs font-bold text-primary-foreground">
                {step.code}
              </span>
              <span className="text-xs font-semibold text-foreground">{step.name}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{step.summary}</p>
          </div>
        ))}
      </section>

      <ConnectionAttentionRadar
        items={attentionConnections}
        onSelectConnection={(id) => navigation.toConnectionDetail(id)}
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <RecentTracesCard
          traces={traces}
          isLoading={tracesView.isLoading}
          onOpenTrace={(traceId) => navigation.toTraceDetail(traceId)}
          onViewAll={() => navigation.toTraces()}
        />
        <RecentStitchRunsCard
          runs={runs}
          isLoading={runsView.isLoading}
          onOpenRun={(runId) => navigation.toStitchRun(runId)}
          onViewAll={() => navigation.toStitches()}
        />
      </div>
    </div>
  );
}
