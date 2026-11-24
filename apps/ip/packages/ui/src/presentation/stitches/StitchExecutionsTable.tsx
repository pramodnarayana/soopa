import {
  Button,
  CopyableIdPill,
  Input,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  Network,
  PlayCircle,
  Search,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import type { StitchRun } from '../../domain/stitch';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';

export interface StitchExecutionsTableProps {
  readonly runs: readonly StitchRun[];
  readonly activeRunId?: string | null;
  readonly isLoading?: boolean;
  readonly onSelectRunId?: (runId: string | null) => void;
  readonly onInspectOnDag?: (runId: string) => void;
  readonly onOpenTrace?: (traceId: string) => void;
  readonly onOpenData?: (traceId: string) => void;
}

type ExecutionStatusFilter = 'ALL' | 'COMPLETED' | 'FAILED' | 'RUNNING';

function matchesStatusCategory(status: string, filter: ExecutionStatusFilter): boolean {
  if (filter === 'ALL') return true;
  const upper = status.toUpperCase();
  if (filter === 'COMPLETED') {
    return upper === 'SUCCEEDED' || upper === 'COMPLETED';
  }
  if (filter === 'FAILED') {
    return upper === 'FAILED' || upper === 'CANCELLED';
  }
  if (filter === 'RUNNING') {
    return upper === 'RUNNING' || upper === 'PENDING' || upper === 'WAITING';
  }
  return false;
}

export function StitchExecutionsTable({
  runs,
  activeRunId,
  isLoading = false,
  onSelectRunId,
  onInspectOnDag,
  onOpenTrace,
  onOpenData,
}: StitchExecutionsTableProps) {
  const [searchFilter, setSearchFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<ExecutionStatusFilter>('ALL');

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      // 1. Status Filter
      if (!matchesStatusCategory(run.status, statusFilter)) return false;

      // 2. Text Search
      if (searchFilter.trim()) {
        const query = searchFilter.toLowerCase();
        const matchesRunId = run.runId.toLowerCase().includes(query);
        const matchesTraceId = run.traceId.toLowerCase().includes(query);
        const matchesPriority = run.priority.toLowerCase().includes(query);
        if (!matchesRunId && !matchesTraceId && !matchesPriority) return false;
      }

      return true;
    });
  }, [runs, statusFilter, searchFilter]);

  const completedCount = useMemo(
    () => runs.filter((r) => matchesStatusCategory(r.status, 'COMPLETED')).length,
    [runs],
  );
  const failedCount = useMemo(
    () => runs.filter((r) => matchesStatusCategory(r.status, 'FAILED')).length,
    [runs],
  );
  const runningCount = useMemo(
    () => runs.filter((r) => matchesStatusCategory(r.status, 'RUNNING')).length,
    [runs],
  );

  return (
    <div className="space-y-4">
      {/* Top Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-xl border border-border bg-card">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search by run ID, trace ID..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </div>

          <div className="flex items-center gap-1 border-l border-border pl-2">
            <Button
              type="button"
              variant={statusFilter === 'ALL' ? 'default' : 'ghost'}
              size="xs"
              onClick={() => setStatusFilter('ALL')}
              className="h-7 text-xs"
            >
              All ({runs.length})
            </Button>
            <Button
              type="button"
              variant={statusFilter === 'COMPLETED' ? 'default' : 'ghost'}
              size="xs"
              onClick={() => setStatusFilter('COMPLETED')}
              className="h-7 text-xs text-emerald-600 dark:text-emerald-400"
            >
              Completed ({completedCount})
            </Button>
            <Button
              type="button"
              variant={statusFilter === 'FAILED' ? 'default' : 'ghost'}
              size="xs"
              onClick={() => setStatusFilter('FAILED')}
              className="h-7 text-xs text-destructive"
            >
              Failed ({failedCount})
            </Button>
            <Button
              type="button"
              variant={statusFilter === 'RUNNING' ? 'default' : 'ghost'}
              size="xs"
              onClick={() => setStatusFilter('RUNNING')}
              className="h-7 text-xs text-brand-ink"
            >
              Running ({runningCount})
            </Button>
          </div>
        </div>

        {activeRunId && (
          <div className="flex items-center gap-2 text-xs bg-primary/10 border border-primary/20 px-3 py-1.5 rounded-lg">
            <span className="font-semibold text-primary">Active on DAG:</span>
            <span className="font-mono text-foreground font-bold">{activeRunId}</span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={() => onSelectRunId?.(null)}
              className="h-5 px-1.5 text-[11px] text-muted-foreground hover:text-foreground"
            >
              Clear
            </Button>
          </div>
        )}
      </div>

      {/* Full-Height Executions Table */}
      <div className="table-wrapper rounded-xl border border-border overflow-hidden bg-card shadow-xs">
        <Table>
          <TableHeader className="bg-muted/70 sticky top-0 z-10">
            <TableRow>
              <TableHead className="text-xs font-semibold w-28">Status</TableHead>
              <TableHead className="text-xs font-semibold w-48">Run ID</TableHead>
              <TableHead className="text-xs font-semibold w-48">Trace ID</TableHead>
              <TableHead className="text-xs font-semibold w-36">Step Progress</TableHead>
              <TableHead className="text-xs font-semibold w-24">Priority</TableHead>
              <TableHead className="text-xs font-semibold w-36">Started</TableHead>
              <TableHead className="text-xs font-semibold text-right w-56">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-16 text-xs text-muted-foreground">
                  Loading workflow executions...
                </TableCell>
              </TableRow>
            ) : filteredRuns.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-16 text-xs text-muted-foreground">
                  <PlayCircle className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
                  <p className="font-medium text-foreground">No workflow executions found</p>
                  <p className="text-muted-foreground text-[11px] mt-0.5">
                    {searchFilter
                      ? 'No runs match the current search filter.'
                      : 'This stitch has not executed any runs yet.'}
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              filteredRuns.map((run) => {
                const isActive = run.runId === activeRunId;
                const completedSteps = run.steps.filter((s) => s.status === 'COMPLETED').length;
                const hasFailures = run.steps.some((s) => s.status === 'FAILED');

                return (
                  <TableRow
                    key={run.runId}
                    className={`hover:bg-muted/50 cursor-pointer text-xs transition-colors ${
                      isActive ? 'bg-primary/10 border-l-2 border-l-primary font-medium' : ''
                    }`}
                    onClick={() => onSelectRunId?.(isActive ? null : run.runId)}
                  >
                    <TableCell className="py-2.5 font-medium">
                      <StatusBadge label={run.status} tone={mapStitchRunStatusTone(run.status)} />
                    </TableCell>

                    <TableCell className="py-2.5 font-mono text-xs">
                      <CopyableIdPill value={run.runId} truncateLength={16} />
                    </TableCell>

                    <TableCell className="py-2.5 font-mono text-xs">
                      <CopyableIdPill value={run.traceId} truncateLength={16} />
                    </TableCell>

                    <TableCell className="py-2.5">
                      <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                        {hasFailures ? (
                          <AlertTriangle className="h-3 w-3 text-destructive shrink-0" />
                        ) : (
                          <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />
                        )}
                        <span>
                          {completedSteps} / {run.steps.length} steps
                        </span>
                      </span>
                    </TableCell>

                    <TableCell className="py-2.5">
                      <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-muted">
                        {run.priority}
                      </span>
                    </TableCell>

                    <TableCell className="py-2.5 text-muted-foreground">
                      {formatRelativeTimestamp(run.createdAt)}
                    </TableCell>

                    <TableCell className="py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          type="button"
                          size="xs"
                          variant={isActive ? 'default' : 'outline'}
                          onClick={() => {
                            if (onInspectOnDag) {
                              onInspectOnDag(run.runId);
                            } else {
                              onSelectRunId?.(isActive ? null : run.runId);
                            }
                          }}
                          className="h-6 text-[11px] gap-1 px-2"
                        >
                          <Network className="h-3 w-3" />
                          <span>{isActive ? 'Active on DAG' : 'Inspect on DAG'}</span>
                        </Button>

                        {onOpenData && (
                          <Button
                            type="button"
                            size="xs"
                            variant="ghost"
                            onClick={() => onOpenData(run.traceId)}
                            className="h-6 px-1.5 text-[11px] gap-1 text-muted-foreground hover:text-foreground"
                            title="View Data for this Run"
                          >
                            <Database className="h-3 w-3" />
                            <span>Data</span>
                          </Button>
                        )}

                        {onOpenTrace && (
                          <Button
                            type="button"
                            size="xs"
                            variant="ghost"
                            onClick={() => onOpenTrace(run.traceId)}
                            className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                            title="Open Waterfall Trace"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
