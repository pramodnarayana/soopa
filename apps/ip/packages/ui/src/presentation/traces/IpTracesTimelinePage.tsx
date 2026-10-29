import {
  type ApiProblem,
  Button,
  Card,
  CardContent,
  CopyableIdPill,
  DataTable,
  Input,
  Label,
  ReplayBadge,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  Switch,
} from '@soopa/ui';
import {
  type ColumnDef,
  getCoreRowModel,
  type RowSelectionState,
  useReactTable,
} from '@tanstack/react-table';
import { Activity, RotateCcw, Search } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useBulkReplayMutation,
  useRecentTracesQuery,
  useSearchTracesByCorrelationQuery,
} from '../../application/use-trace-queries';
import { ReplayStage, type ReplayStageValue, TraceStatus } from '../../domain/enums';
import type { IpTraceLineageItem } from '../../domain/trace';
import { isReplayStageValue } from '../../domain/type-guards';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { LayerTagBadge } from '../shared/FiveLayerStagePill';
import { IpPageHeader } from '../shared/IpPageHeader';
import {
  formatRelativeTimestamp,
  formatReplayStageLabel,
  mapTraceStatusTone,
} from '../shared/status-mapping';

const STATUS_FILTER_ALL = 'ALL';

const STATUS_OPTIONS: ReadonlyArray<{ readonly value: string; readonly label: string }> = [
  { value: STATUS_FILTER_ALL, label: 'All Statuses' },
  { value: TraceStatus.DELIVERED, label: 'Delivered (L5)' },
  { value: TraceStatus.FAILED, label: 'Failed' },
  { value: TraceStatus.REJECTED, label: 'Rejected (L2/L3)' },
  { value: TraceStatus.NORMALIZED, label: 'Normalized (L3)' },
  { value: TraceStatus.REPLICATED, label: 'Replicated (L2)' },
  { value: TraceStatus.INGESTED, label: 'Ingested (L1)' },
];

const BULK_STAGE_OPTIONS: readonly ReplayStageValue[] = [
  ReplayStage.RETRY_DELIVER,
  ReplayStage.RETRY_STITCH,
  ReplayStage.RETRY_NORMALIZE,
  ReplayStage.RETRY_INGEST,
];

export interface IpTracesTimelinePageProps {
  readonly initialCorrelationQuery?: string;
}

function BulkReplayCommandBar({
  selectedTraceIds,
  onClearSelection,
  onProblem,
}: {
  readonly selectedTraceIds: readonly string[];
  readonly onClearSelection: () => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}) {
  const [stage, setStage] = useState<ReplayStageValue>(ReplayStage.RETRY_DELIVER);
  const bulkMutation = useBulkReplayMutation();

  if (selectedTraceIds.length === 0) {
    return null;
  }

  const handleBulkReplay = async (): Promise<void> => {
    onProblem(null);
    const res = await bulkMutation.mutateAsync({
      traceIds: selectedTraceIds.slice(0, 100),
      stage,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(
      `Replayed ${res.value.replayedCount} trace(s) at ${stage} (${res.value.failedItems.length} skipped).`,
    );
    onClearSelection();
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary bg-accent px-4 py-3 text-accent-foreground shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <RotateCcw className="h-4 w-4 text-brand-ink" />
        <span>{selectedTraceIds.length} trace(s) selected for deterministic bulk replay</span>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="w-64">
          <Select
            value={stage}
            onValueChange={(v) => {
              if (isReplayStageValue(v)) {
                setStage(v);
              }
            }}
          >
            <SelectTrigger aria-label="Bulk replay target stage" className="h-9 bg-card text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BULK_STAGE_OPTIONS.map((opt) => (
                <SelectItem key={opt} value={opt}>
                  {formatReplayStageLabel(opt)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          type="button"
          size="sm"
          disabled={bulkMutation.isPending}
          onClick={() => void handleBulkReplay()}
        >
          {bulkMutation.isPending ? 'Dispatching...' : 'Execute Bulk Replay'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClearSelection}>
          Clear
        </Button>
      </div>
    </div>
  );
}

export function IpTracesTimelinePage({ initialCorrelationQuery = '' }: IpTracesTimelinePageProps) {
  const { navigation } = useIpWorkspace();
  const [correlationInput, setCorrelationInput] = useState(initialCorrelationQuery);
  const [statusFilter, setStatusFilter] = useState<string>(STATUS_FILTER_ALL);
  const [replayedOnly, setReplayedOnly] = useState(false);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [mutationProblem, setMutationProblem] = useState<ApiProblem | null>(null);

  const trimmedQuery = correlationInput.trim();
  const isSearchMode = trimmedQuery.length > 0;

  const recentView = useRecentTracesQuery(
    {
      status: statusFilter === STATUS_FILTER_ALL ? undefined : statusFilter,
      minReplayCount: replayedOnly ? 1 : undefined,
      limit: 75,
    },
    !isSearchMode,
  );
  const searchView = useSearchTracesByCorrelationQuery(trimmedQuery, 75);

  const activeView = isSearchMode ? searchView : recentView;
  const rowsData = useMemo(() => [...(activeView.data ?? [])], [activeView.data]);

  const columns = useMemo<ColumnDef<IpTraceLineageItem>[]>(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <input
            type="checkbox"
            aria-label="Select all traces"
            checked={table.getIsAllRowsSelected()}
            onChange={table.getToggleAllRowsSelectedHandler()}
            onClick={(e) => e.stopPropagation()}
            className="h-4 w-4 rounded border-border"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={`Select trace ${row.original.traceId}`}
            checked={row.getIsSelected()}
            onChange={row.getToggleSelectedHandler()}
            onClick={(e) => e.stopPropagation()}
            className="h-4 w-4 rounded border-border"
          />
        ),
      },
      {
        accessorKey: 'traceId',
        header: 'Trace ID',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <CopyableIdPill value={row.original.traceId} truncateLength={22} />
            <ReplayBadge count={row.original.replayCount} />
          </div>
        ),
      },
      {
        accessorKey: 'correlationId',
        header: 'Business Correlation ID',
        cell: ({ row }) =>
          row.original.correlationId ? (
            <CopyableIdPill value={row.original.correlationId} />
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        accessorKey: 'primaryLayer',
        header: 'Pipeline Stage',
        cell: ({ row }) => <LayerTagBadge layer={row.original.primaryLayer} />,
      },
      {
        accessorKey: 'status',
        header: 'Outcome',
        cell: ({ row }) => (
          <StatusBadge label={row.original.status} tone={mapTraceStatusTone(row.original.status)} />
        ),
      },
      {
        accessorKey: 'originalTraceId',
        header: 'Root Origin',
        cell: ({ row }) =>
          row.original.originalTraceId && row.original.originalTraceId !== row.original.traceId ? (
            <CopyableIdPill value={row.original.originalTraceId} truncateLength={16} />
          ) : (
            <span className="text-xs text-muted-foreground">Root Attempt</span>
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

  const table = useReactTable({
    data: rowsData,
    columns,
    state: { rowSelection },
    onRowSelectionChange: setRowSelection,
    getRowId: (row) => row.traceId,
    getCoreRowModel: getCoreRowModel(),
  });

  const selectedIds = table.getSelectedRowModel().rows.map((row) => row.original.traceId);

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Support Audit Ledger"
        title="Support Timeline & Deterministic Replay"
        subtitle="Query business correlation keys in <15ms across L1→L5, inspect replay lineage trees, or execute bulk deterministic recovery."
      />

      <ApiProblemBanner
        problem={mutationProblem ?? activeView.problem}
        onRetry={() => void activeView.refetch()}
      />

      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-4 md:grid-cols-12 md:items-end">
          <div className="space-y-1.5 md:col-span-6">
            <Label htmlFor="ip-correlation-search">Business Correlation Key</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-2.5 left-3 h-4 w-4 text-muted-foreground" />
              <Input
                id="ip-correlation-search"
                value={correlationInput}
                onChange={(e) => setCorrelationInput(e.target.value)}
                placeholder="Filter by exact business correlation ID (e.g. MTR-700, ORD-1042)..."
                className="pl-9 font-mono text-sm"
              />
            </div>
          </div>

          <div className="space-y-1.5 md:col-span-4">
            <Label>Trace Status</Label>
            <Select value={statusFilter} onValueChange={setStatusFilter} disabled={isSearchMode}>
              <SelectTrigger aria-label="Filter trace status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2.5 pb-2 md:col-span-2">
            <Switch
              id="replayed-only-toggle"
              checked={replayedOnly}
              disabled={isSearchMode}
              onCheckedChange={setReplayedOnly}
            />
            <Label htmlFor="replayed-only-toggle" className="cursor-pointer text-xs">
              Replayed Only
            </Label>
          </div>
        </CardContent>
      </Card>

      <BulkReplayCommandBar
        selectedTraceIds={selectedIds}
        onClearSelection={() => setRowSelection({})}
        onProblem={setMutationProblem}
      />

      <DataTable
        table={table}
        columnsLength={columns.length}
        isLoading={activeView.isLoading}
        dataLength={rowsData.length}
        ariaLabel="Integration Platform support traces"
        emptyIcon={<Activity className="h-6 w-6" />}
        emptyTitle={
          isSearchMode ? `No Traces Matched "${trimmedQuery}"` : 'No Support Traces Found'
        }
        emptyDescription="Adjust the correlation query or status filter to locate historical integration traces."
        onRowClick={(row) => navigation.toTraceDetail(row.original.traceId)}
      />
    </div>
  );
}
