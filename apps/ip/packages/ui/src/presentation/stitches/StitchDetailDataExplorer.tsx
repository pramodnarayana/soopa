import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  cn,
  Input,
  MonacoCodeViewer,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Database,
  ExternalLink,
  FileCode2,
  FileText,
  Filter,
  Layers,
  PlayCircle,
  Radio,
  RotateCcw,
  Search,
  Send,
  X,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useGemRecordsQuery,
  useInboundRecordsQuery,
  useNormalizedRecordsQuery,
  useOutboundRecordsQuery,
  useReplicaRecordsQuery,
} from '../../application/use-record-queries';
import { useStitchRunsQuery } from '../../application/use-stitch-queries';
import { useReplayTransactionMutation } from '../../application/use-trace-queries';
import { ReplayStage } from '../../domain/enums';
import {
  isTransactionalStitch,
  type Stitch,
  type StitchDefinition,
  type StitchRun,
} from '../../domain/stitch';
import {
  formatBytesCompact,
  formatRelativeTimestamp,
  mapStitchRunStatusTone,
  stringifyJsonPretty,
} from '../shared/status-mapping';

export type DataPlaneTab = 'executions' | 'inbound' | 'replica' | 'normalized' | 'outbound' | 'gem';

export interface StitchDetailDataExplorerProps {
  readonly stitch?: Stitch | null;
  readonly definition?: StitchDefinition | null;
  readonly activeTab: DataPlaneTab;
  readonly onTabChange: (tab: DataPlaneTab) => void;
  readonly onOpenTrace?: (traceId: string) => void;
  readonly selectedNodeKey?: string | null;
  readonly onClearNodeFilter?: () => void;
  readonly runs?: readonly StitchRun[];
  readonly isRunsLoading?: boolean;
  readonly activeRunId?: string | null;
  readonly onSelectRunId?: (runId: string | null) => void;
}

interface SelectedRecordDetail {
  readonly title: string;
  readonly payloadJson: string;
  readonly errorMessage?: string | null;
  readonly failureCategory?: string | null;
  readonly retryAfterSeconds?: number | null;
  readonly traceId?: string | null;
  readonly statusCode?: number | null;
  readonly isFailed?: boolean;
}

export function StitchDetailDataExplorer({
  stitch,
  definition,
  activeTab,
  onTabChange,
  onOpenTrace: _onOpenTrace,
  selectedNodeKey,
  onClearNodeFilter,
  runs: propRuns,
  isRunsLoading: propRunsLoading,
  activeRunId,
  onSelectRunId,
}: StitchDetailDataExplorerProps) {
  const [searchFilter, setSearchFilter] = useState('');
  const [executionStatusFilter, setExecutionStatusFilter] = useState<
    'ALL' | 'COMPLETED' | 'FAILED' | 'RUNNING'
  >('ALL');
  const [selectedRecordDetail, setSelectedRecordDetail] = useState<SelectedRecordDetail | null>(
    null,
  );

  const fallbackRunsQuery = useStitchRunsQuery(
    definition?.workflowId ? { workflowId: definition.workflowId } : undefined,
  );
  const effectiveRuns = propRuns ?? fallbackRunsQuery.data ?? [];
  const effectiveRunsLoading =
    propRuns !== undefined ? (propRunsLoading ?? false) : fallbackRunsQuery.isLoading;

  const filteredRuns = useMemo(() => {
    let result = [...effectiveRuns];
    if (executionStatusFilter !== 'ALL') {
      result = result.filter((r) => r.status.toUpperCase() === executionStatusFilter);
    }
    if (searchFilter.trim()) {
      const q = searchFilter.toLowerCase().trim();
      result = result.filter(
        (r) =>
          r.runId.toLowerCase().includes(q) ||
          r.traceId.toLowerCase().includes(q) ||
          r.status.toLowerCase().includes(q) ||
          Boolean(r.correlationId && r.correlationId.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [effectiveRuns, executionStatusFilter, searchFilter]);

  const replayMutation = useReplayTransactionMutation();

  const handle1ClickReplay = async (traceId: string) => {
    try {
      const res = await replayMutation.mutateAsync({
        traceId,
        stage: ReplayStage.RETRY_DELIVER,
      });
      if (res.ok) {
        toast.success(`1-Click Replay initiated: child trace ${res.value.newTraceId}`);
      } else {
        toast.error(`Replay failed: ${res.error.message}`);
      }
    } catch {
      toast.error('Replay request failed');
    }
  };

  const isTransactional = useMemo(
    () => isTransactionalStitch(stitch, definition),
    [stitch, definition],
  );

  const canonicalType = stitch?.canonicalEventType;
  const entityDomain = canonicalType ? canonicalType.split('.')[0] : undefined;

  // L1: Inbound wire records
  const inboundQuery = useInboundRecordsQuery(
    { limit: 100, hydratePayloads: true },
    activeTab === 'inbound',
  );

  // L2: Replica staging records
  const replicaQuery = useReplicaRecordsQuery({ limit: 100 }, activeTab === 'replica');

  // L3: Normalized records
  const normalizedQuery = useNormalizedRecordsQuery(
    { canonicalType, limit: 100 },
    activeTab === 'normalized',
  );

  // L5: Outbound wire delivery records
  const outboundQuery = useOutboundRecordsQuery(
    { limit: 100, hydratePayloads: true },
    activeTab === 'outbound',
  );

  // GEM: Identity crosswalk (only queried if this stitch is transactional)
  const gemQuery = useGemRecordsQuery(
    { entityDomain, limit: 100 },
    activeTab === 'gem' && isTransactional,
  );

  // Filtered rows for Inbound
  const inboundRows = useMemo(() => {
    let data = inboundQuery.data ?? [];
    if (selectedNodeKey) {
      const k = selectedNodeKey.toLowerCase();
      data = data.filter(
        (r) =>
          r.streamName.toLowerCase().includes(k) ||
          r.connectionId.toLowerCase().includes(k) ||
          k.includes(r.streamName.toLowerCase()),
      );
    }
    if (!searchFilter.trim()) return [...data];
    const q = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        r.streamName.toLowerCase().includes(q) ||
        r.connectionId.toLowerCase().includes(q),
    );
  }, [inboundQuery.data, searchFilter, selectedNodeKey]);

  // Filtered rows for Replica
  const replicaRows = useMemo(() => {
    let data = replicaQuery.data ?? [];
    if (selectedNodeKey) {
      const k = selectedNodeKey.toLowerCase();
      data = data.filter(
        (r) =>
          r.stream.toLowerCase().includes(k) ||
          r.connectionId.toLowerCase().includes(k) ||
          k.includes(r.stream.toLowerCase()),
      );
    }
    if (!searchFilter.trim()) return [...data];
    const q = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        r.stream.toLowerCase().includes(q) ||
        JSON.stringify(r.data).toLowerCase().includes(q),
    );
  }, [replicaQuery.data, searchFilter, selectedNodeKey]);

  // Filtered rows for Normalized
  const normalizedRows = useMemo(() => {
    let data = normalizedQuery.data ?? [];
    if (selectedNodeKey) {
      const k = selectedNodeKey.toLowerCase();
      data = data.filter(
        (r) =>
          r.canonicalType.toLowerCase().includes(k) ||
          r.sourceId.toLowerCase().includes(k) ||
          k.includes(r.canonicalType.toLowerCase()),
      );
    }
    if (!searchFilter.trim()) return [...data];
    const q = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        r.sourceId.toLowerCase().includes(q) ||
        r.canonicalType.toLowerCase().includes(q) ||
        JSON.stringify(r.canonicalData).toLowerCase().includes(q),
    );
  }, [normalizedQuery.data, searchFilter, selectedNodeKey]);

  // Filtered rows for Outbound
  const outboundRows = useMemo(() => {
    let data = outboundQuery.data ?? [];
    if (selectedNodeKey) {
      const k = selectedNodeKey.toLowerCase();
      data = data.filter(
        (r) =>
          r.appId.toLowerCase().includes(k) ||
          r.operation.toLowerCase().includes(k) ||
          r.streamName.toLowerCase().includes(k) ||
          k.includes(r.appId.toLowerCase()),
      );
    }
    if (!searchFilter.trim()) return [...data];
    const q = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        r.appId.toLowerCase().includes(q) ||
        r.operation.toLowerCase().includes(q) ||
        r.targetUrl.toLowerCase().includes(q) ||
        (r.errorMessage && r.errorMessage.toLowerCase().includes(q)) ||
        (r.correlationId && r.correlationId.toLowerCase().includes(q)),
    );
  }, [outboundQuery.data, searchFilter, selectedNodeKey]);

  // Filtered rows for GEM
  const gemRows = useMemo(() => {
    const data = gemQuery.data ?? [];
    if (!searchFilter.trim()) return [...data];
    const q = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.canonicalId.toLowerCase().includes(q) ||
        r.sourceEntityId.toLowerCase().includes(q) ||
        (r.destEntityId && r.destEntityId.toLowerCase().includes(q)) ||
        r.entityDomain.toLowerCase().includes(q),
    );
  }, [gemQuery.data, searchFilter]);

  return (
    <Card className="rounded-xl border border-border shadow-sm">
      <CardHeader className="pb-3 border-b border-border/60">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-semibold">Data Records</CardTitle>
            {isTransactional && (
              <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary">
                Transactional GEM Enabled
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
              <Input
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Filter records..."
                className="h-8 pl-8 text-xs w-48 sm:w-60"
              />
            </div>
            {searchFilter && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setSearchFilter('')}
                className="h-8 px-2 text-xs"
              >
                Clear
              </Button>
            )}
          </div>
        </div>

        {/* Contextual DAG Node Lens Banner */}
        {selectedNodeKey && (
          <div className="mt-3 flex items-center justify-between px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/25 text-xs">
            <span className="flex items-center gap-2 text-foreground font-medium">
              <span>🔍 Scoped to DAG Node:</span>
              <code className="font-mono font-semibold bg-background px-2 py-0.5 rounded border border-border">
                {selectedNodeKey}
              </code>
            </span>
            {onClearNodeFilter && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onClearNodeFilter}
                className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                Clear Scoped Lens
              </Button>
            )}
          </div>
        )}

        {/* Tab switcher in exact required order: Inbound -> Replica -> Normalized -> Outbound -> GEM (only if transactional) */}
        <div className="pt-2">
          <Tabs value={activeTab} onValueChange={(val) => onTabChange(val as DataPlaneTab)}>
            <TabsList className="h-8">
              {/* TAB 0: EXECUTIONS */}
              <TabsTrigger value="executions" className="text-xs gap-1.5">
                <PlayCircle className="h-3.5 w-3.5 text-emerald-500" />
                <span>Executions</span>
                <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                  {effectiveRuns.length}
                </span>
              </TabsTrigger>

              {/* TAB 1: INBOUND */}
              <TabsTrigger value="inbound" className="text-xs gap-1.5">
                <Radio className="h-3.5 w-3.5 text-blue-500" />
                <span>Inbound</span>
                <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                  {inboundRows.length}
                </span>
              </TabsTrigger>

              {/* TAB 2: REPLICA */}
              <TabsTrigger value="replica" className="text-xs gap-1.5">
                <Layers className="h-3.5 w-3.5 text-purple-500" />
                <span>Replica</span>
                <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                  {replicaRows.length}
                </span>
              </TabsTrigger>

              {/* TAB 3: RECORDS */}
              <TabsTrigger value="normalized" className="text-xs gap-1.5">
                <Database className="h-3.5 w-3.5 text-emerald-500" />
                <span>Records</span>
                <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                  {normalizedRows.length}
                </span>
              </TabsTrigger>

              {/* TAB 4: OUTBOUND */}
              <TabsTrigger value="outbound" className="text-xs gap-1.5">
                <Send className="h-3.5 w-3.5 text-cyan-500" />
                <span>Outbound</span>
                <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                  {outboundRows.length}
                </span>
              </TabsTrigger>

              {/* TAB 5: MAPPINGS (ONLY IF TRANSACTIONAL) */}
              {isTransactional && (
                <TabsTrigger value="gem" className="text-xs gap-1.5">
                  <ArrowRightLeft className="h-3.5 w-3.5 text-amber-500" />
                  <span>Mappings</span>
                  <span className="font-mono text-[10px] ml-1 px-1.5 py-0.2 bg-muted rounded-full">
                    {gemRows.length}
                  </span>
                </TabsTrigger>
              )}
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-4">
        {/* TAB 0: EXECUTIONS (RUNS) */}
        {activeTab === 'executions' && (
          <div className="space-y-3">
            {/* Filter & Search Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3">
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
                    variant={executionStatusFilter === 'ALL' ? 'default' : 'ghost'}
                    size="xs"
                    onClick={() => setExecutionStatusFilter('ALL')}
                    className="h-7 text-xs"
                  >
                    All ({effectiveRuns.length})
                  </Button>
                  <Button
                    type="button"
                    variant={executionStatusFilter === 'COMPLETED' ? 'default' : 'ghost'}
                    size="xs"
                    onClick={() => setExecutionStatusFilter('COMPLETED')}
                    className="h-7 text-xs text-emerald-600 dark:text-emerald-400"
                  >
                    Completed (
                    {effectiveRuns.filter((r) => r.status.toUpperCase() === 'COMPLETED').length})
                  </Button>
                  <Button
                    type="button"
                    variant={executionStatusFilter === 'FAILED' ? 'default' : 'ghost'}
                    size="xs"
                    onClick={() => setExecutionStatusFilter('FAILED')}
                    className="h-7 text-xs text-destructive"
                  >
                    Failed (
                    {effectiveRuns.filter((r) => r.status.toUpperCase() === 'FAILED').length})
                  </Button>
                  <Button
                    type="button"
                    variant={executionStatusFilter === 'RUNNING' ? 'default' : 'ghost'}
                    size="xs"
                    onClick={() => setExecutionStatusFilter('RUNNING')}
                    className="h-7 text-xs text-brand-ink"
                  >
                    Running (
                    {effectiveRuns.filter((r) => r.status.toUpperCase() === 'RUNNING').length})
                  </Button>
                </div>
              </div>

              {activeRunId && (
                <div className="flex items-center gap-2 text-xs bg-primary/10 border border-primary/20 px-2.5 py-1 rounded-lg">
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

            {/* Executions Table */}
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold w-28">Status</TableHead>
                    <TableHead className="text-xs font-semibold w-48">Run ID</TableHead>
                    <TableHead className="text-xs font-semibold w-48">Trace ID</TableHead>
                    <TableHead className="text-xs font-semibold w-36">Step Progress</TableHead>
                    <TableHead className="text-xs font-semibold w-24">Priority</TableHead>
                    <TableHead className="text-xs font-semibold w-36">Started</TableHead>
                    <TableHead className="text-xs font-semibold text-right w-44">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {effectiveRunsLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading workflow executions...
                      </TableCell>
                    </TableRow>
                  ) : filteredRuns.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No workflow executions match the current filter.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredRuns.map((run) => {
                      const isActive = run.runId === activeRunId;
                      const completedSteps = run.steps.filter(
                        (s) => s.status === 'COMPLETED',
                      ).length;
                      const hasFailures = run.steps.some((s) => s.status === 'FAILED');

                      return (
                        <TableRow
                          key={run.runId}
                          className={cn(
                            'hover:bg-muted/50 cursor-pointer text-xs transition-colors',
                            isActive && 'bg-primary/10 border-l-2 border-l-primary font-medium',
                          )}
                          onClick={() => onSelectRunId?.(isActive ? null : run.runId)}
                        >
                          <TableCell className="py-2.5 font-medium">
                            <StatusBadge
                              label={run.status}
                              tone={mapStitchRunStatusTone(run.status)}
                            />
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

                          <TableCell
                            className="py-2.5 text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              <Button
                                type="button"
                                size="xs"
                                variant={isActive ? 'secondary' : 'outline'}
                                onClick={() => onSelectRunId?.(isActive ? null : run.runId)}
                                className="h-6 text-[11px] gap-1"
                              >
                                {isActive ? (
                                  <>
                                    <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                                    <span>Active</span>
                                  </>
                                ) : (
                                  <span>Inspect on DAG</span>
                                )}
                              </Button>

                              {_onOpenTrace && (
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={() => _onOpenTrace(run.traceId)}
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
        )}

        {/* TAB 1: INBOUND WIRE (L1) */}
        {activeTab === 'inbound' && (
          <div className="space-y-3">
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold w-36">Wire Record ID</TableHead>
                    <TableHead className="text-xs font-semibold w-40">Stream / App</TableHead>
                    <TableHead className="text-xs font-semibold w-52">Request</TableHead>
                    <TableHead className="text-xs font-semibold w-48">Response</TableHead>
                    <TableHead className="text-xs font-semibold w-32">Ingested At</TableHead>
                    <TableHead className="text-xs font-semibold text-right w-28">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inboundQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading inbound wire records...
                      </TableCell>
                    </TableRow>
                  ) : inboundRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No inbound wire records found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    inboundRows.map((row) => {
                      const isError =
                        row.responseStatusCode != null && row.responseStatusCode >= 400;
                      return (
                        <TableRow
                          key={row.id}
                          onClick={() => {
                            setSelectedRecordDetail({
                              title: `Inbound Wire Record: ${row.id}`,
                              payloadJson: stringifyJsonPretty(
                                row.requestBody ?? {
                                  sha256: row.requestSha256,
                                  connectionId: row.connectionId,
                                  stream: row.streamName,
                                },
                              ),
                            });
                          }}
                          className="cursor-pointer hover:bg-muted/50"
                        >
                          <TableCell className="font-mono text-xs font-medium">
                            <CopyableIdPill value={row.id} truncateLength={14} />
                          </TableCell>

                          <TableCell className="font-mono text-xs">
                            <div className="font-semibold text-foreground">{row.streamName}</div>
                            <div className="text-[10px] text-muted-foreground truncate">
                              {row.connectionId}
                            </div>
                          </TableCell>

                          {/* Request Column */}
                          <TableCell className="text-xs" onClick={(e) => e.stopPropagation()}>
                            <div className="space-y-1">
                              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                                <span className="font-bold text-foreground">
                                  {row.ingestionMode || 'WEBHOOK'}
                                </span>
                                <span className="text-muted-foreground">
                                  · {formatBytesCompact(row.requestSizeBytes)}
                                </span>
                              </div>
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                className="h-6 text-[11px] gap-1 px-2"
                                onClick={() => {
                                  setSelectedRecordDetail({
                                    title: `Inbound Request (${row.id})`,
                                    payloadJson: stringifyJsonPretty(
                                      row.requestBody ?? {
                                        headers: row.requestHeaders,
                                        sha256: row.requestSha256,
                                        sizeBytes: row.requestSizeBytes,
                                        ingestionMode: row.ingestionMode,
                                      },
                                    ),
                                  });
                                }}
                              >
                                <FileCode2 className="h-3 w-3 text-blue-500" />
                                <span>Request</span>
                              </Button>
                            </div>
                          </TableCell>

                          {/* Response Column */}
                          <TableCell className="text-xs" onClick={(e) => e.stopPropagation()}>
                            <div className="space-y-1">
                              <div className="flex items-center gap-1.5">
                                <StatusBadge
                                  label={
                                    row.responseStatusCode
                                      ? `HTTP ${row.responseStatusCode}`
                                      : '200 OK'
                                  }
                                  tone={isError ? StatusTone.CRITICAL : StatusTone.HEALTHY}
                                />
                                {row.durationMs != null && (
                                  <span className="font-mono text-[11px] text-muted-foreground">
                                    {row.durationMs}ms
                                  </span>
                                )}
                              </div>
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                className="h-6 text-[11px] gap-1 px-2"
                                onClick={() => {
                                  setSelectedRecordDetail({
                                    title: `Inbound Response (${row.id})`,
                                    payloadJson: stringifyJsonPretty(
                                      row.responseBody ?? {
                                        statusCode: row.responseStatusCode ?? 200,
                                        status: isError ? 'REJECTED' : 'ACCEPTED',
                                        traceId: row.traceId,
                                        durationMs: row.durationMs,
                                        headers: row.responseHeaders ?? {},
                                      },
                                    ),
                                    statusCode: row.responseStatusCode ?? 200,
                                    isFailed: isError,
                                  });
                                }}
                              >
                                <FileText className="h-3 w-3 text-emerald-500" />
                                <span>Response</span>
                              </Button>
                            </div>
                          </TableCell>

                          <TableCell className="text-xs text-muted-foreground font-mono">
                            {formatRelativeTimestamp(row.receivedAt)}
                          </TableCell>

                          <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                            {_onOpenTrace && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs text-primary"
                                onClick={() => _onOpenTrace(row.traceId)}
                                title="Open Trace Waterfall"
                              >
                                <ExternalLink className="h-3.5 w-3.5 mr-1" />
                                <span>Trace</span>
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {/* TAB 2: REPLICA STAGING (L2) */}
        {activeTab === 'replica' && (
          <div className="space-y-3">
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold">Replica ID</TableHead>
                    <TableHead className="text-xs font-semibold">Stream</TableHead>
                    <TableHead className="text-xs font-semibold">Raw Staged Payload</TableHead>
                    <TableHead className="text-xs font-semibold">Staged At</TableHead>
                    <TableHead className="text-xs font-semibold text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {replicaQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading replica staging records...
                      </TableCell>
                    </TableRow>
                  ) : replicaRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No replica staging records found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    replicaRows.map((row) => (
                      <TableRow
                        key={row.id}
                        onClick={() => {
                          setSelectedRecordDetail({
                            title: `Replica Staging Record: ${row.id}`,
                            payloadJson: stringifyJsonPretty(row.data),
                          });
                        }}
                        className="cursor-pointer hover:bg-muted/50"
                      >
                        <TableCell className="font-mono text-xs font-medium">{row.id}</TableCell>
                        <TableCell className="font-mono text-xs">{row.stream}</TableCell>
                        <TableCell className="font-mono text-xs max-w-md truncate text-muted-foreground">
                          {JSON.stringify(row.data).slice(0, 80)}...
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground font-mono">
                          {formatRelativeTimestamp(row.updatedAt)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-primary"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRecordDetail({
                                title: `Replica Staging Record: ${row.id}`,
                                payloadJson: stringifyJsonPretty(row.data),
                              });
                            }}
                          >
                            <FileCode2 className="h-3.5 w-3.5 mr-1" />
                            Payload
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {/* TAB 3: BUSINESS RECORDS (L3) */}
        {activeTab === 'normalized' && (
          <div className="space-y-3">
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold">Record ID</TableHead>
                    <TableHead className="text-xs font-semibold">Entity Type</TableHead>
                    <TableHead className="text-xs font-semibold">Key Payload Attributes</TableHead>
                    <TableHead className="text-xs font-semibold">Processed At</TableHead>
                    <TableHead className="text-xs font-semibold text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {normalizedQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading records...
                      </TableCell>
                    </TableRow>
                  ) : normalizedRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No business records found matching current criteria.
                      </TableCell>
                    </TableRow>
                  ) : (
                    normalizedRows.map((row) => (
                      <TableRow
                        key={row.id}
                        onClick={() => {
                          setSelectedRecordDetail({
                            title: `Business Record: ${row.id}`,
                            payloadJson: stringifyJsonPretty(row.canonicalData),
                          });
                        }}
                        className="cursor-pointer hover:bg-muted/50"
                      >
                        <TableCell className="font-mono text-xs font-semibold text-foreground">
                          {row.id}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          <StatusBadge label={row.canonicalType} tone={StatusTone.HEALTHY} />
                        </TableCell>
                        <TableCell className="font-mono text-xs max-w-md truncate text-muted-foreground">
                          {JSON.stringify(row.canonicalData).slice(0, 80)}...
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground font-mono">
                          {formatRelativeTimestamp(row.normalizedAt)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-primary"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRecordDetail({
                                title: `Business Record: ${row.id}`,
                                payloadJson: stringifyJsonPretty(row.canonicalData),
                              });
                            }}
                          >
                            <FileCode2 className="h-3.5 w-3.5 mr-1" />
                            JSON
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {/* TAB 4: OUTBOUND DELIVERIES (L5) */}
        {activeTab === 'outbound' && (
          <div className="space-y-3">
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold w-36">Destination App</TableHead>
                    <TableHead className="text-xs font-semibold w-28">Status</TableHead>
                    <TableHead className="text-xs font-semibold w-52">Request</TableHead>
                    <TableHead className="text-xs font-semibold w-52">Response</TableHead>
                    <TableHead className="text-xs font-semibold w-32">Sent At</TableHead>
                    <TableHead className="text-xs font-semibold text-right w-36">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {outboundQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading outbound delivery ledger records...
                      </TableCell>
                    </TableRow>
                  ) : outboundRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No outbound delivery records found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    outboundRows.map((row) => {
                      const isFailed = row.status === 'FAILED' || Boolean(row.errorMessage);
                      return (
                        <TableRow
                          key={row.id}
                          className={cn(
                            'cursor-pointer transition-colors',
                            isFailed
                              ? 'bg-status-critical-bg/10 hover:bg-status-critical-bg/20'
                              : 'hover:bg-muted/40',
                          )}
                          onClick={() => {
                            setSelectedRecordDetail({
                              title: `Outbound Delivery: ${row.appId} (${row.operation})`,
                              payloadJson: stringifyJsonPretty({
                                targetUrl: row.targetUrl,
                                httpMethod: row.httpMethod,
                                requestHeaders: row.requestHeaders,
                                requestBody: row.requestBody,
                                responseHeaders: row.responseHeaders,
                                responseBody: row.responseBody,
                              }),
                              errorMessage: row.errorMessage,
                              failureCategory: row.failureCategory,
                              retryAfterSeconds: row.retryAfterSeconds,
                              traceId: row.traceId,
                              statusCode: row.responseStatusCode,
                              isFailed,
                            });
                          }}
                        >
                          <TableCell className="font-mono text-xs">
                            <div className="font-semibold text-foreground">{row.appId}</div>
                            <div className="text-[10px] text-muted-foreground">{row.operation}</div>
                          </TableCell>

                          <TableCell>
                            <StatusBadge
                              label={row.status}
                              tone={
                                row.status === 'DELIVERED'
                                  ? StatusTone.HEALTHY
                                  : row.status === 'FAILED'
                                    ? StatusTone.CRITICAL
                                    : StatusTone.WARNING
                              }
                            />
                          </TableCell>

                          {/* Request Column */}
                          <TableCell className="text-xs" onClick={(e) => e.stopPropagation()}>
                            <div className="space-y-1">
                              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                                <span className="font-bold text-foreground">
                                  {row.httpMethod || 'POST'}
                                </span>
                                <span
                                  className="text-muted-foreground truncate max-w-[160px]"
                                  title={row.targetUrl}
                                >
                                  {row.targetUrl}
                                </span>
                              </div>
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                className="h-6 text-[11px] gap-1 px-2"
                                onClick={() => {
                                  setSelectedRecordDetail({
                                    title: `Outbound Request (${row.appId})`,
                                    payloadJson: stringifyJsonPretty(
                                      row.requestBody ?? {
                                        url: row.targetUrl,
                                        method: row.httpMethod,
                                        headers: row.requestHeaders,
                                        sizeBytes: row.requestSizeBytes,
                                      },
                                    ),
                                    statusCode: row.responseStatusCode,
                                  });
                                }}
                              >
                                <FileCode2 className="h-3 w-3 text-cyan-500" />
                                <span>Request</span>
                              </Button>
                            </div>
                          </TableCell>

                          {/* Response Column */}
                          <TableCell className="text-xs" onClick={(e) => e.stopPropagation()}>
                            <div className="space-y-1">
                              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                                {row.responseStatusCode ? (
                                  <StatusBadge
                                    label={`HTTP ${row.responseStatusCode}`}
                                    tone={
                                      row.responseStatusCode >= 200 && row.responseStatusCode < 300
                                        ? StatusTone.HEALTHY
                                        : StatusTone.CRITICAL
                                    }
                                  />
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                                {row.durationMs != null && (
                                  <span className="text-muted-foreground font-mono">
                                    {row.durationMs}ms
                                  </span>
                                )}
                              </div>
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                className="h-6 text-[11px] gap-1 px-2"
                                onClick={() => {
                                  setSelectedRecordDetail({
                                    title: `Outbound Response (${row.appId})`,
                                    payloadJson: stringifyJsonPretty(
                                      row.responseBody ?? {
                                        statusCode: row.responseStatusCode,
                                        status: row.status,
                                        errorMessage: row.errorMessage,
                                        headers: row.responseHeaders,
                                      },
                                    ),
                                    errorMessage: row.errorMessage,
                                    failureCategory: row.failureCategory,
                                    statusCode: row.responseStatusCode,
                                    isFailed,
                                  });
                                }}
                              >
                                <FileText className="h-3 w-3 text-emerald-500" />
                                <span>Response</span>
                              </Button>
                            </div>
                          </TableCell>

                          <TableCell className="text-xs text-muted-foreground font-mono">
                            {formatRelativeTimestamp(row.sentAt)}
                          </TableCell>

                          <TableCell className="text-right">
                            <div
                              className="flex items-center justify-end gap-1.5"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {isFailed && (
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  disabled={replayMutation.isPending}
                                  className="h-7 px-2 text-xs gap-1 border-status-critical-border text-status-critical-fg hover:bg-status-critical-bg"
                                  onClick={() => handle1ClickReplay(row.traceId)}
                                >
                                  <RotateCcw className="h-3 w-3" />
                                  <span>1-Click Replay</span>
                                </Button>
                              )}
                              {_onOpenTrace && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-xs text-primary"
                                  onClick={() => _onOpenTrace(row.traceId)}
                                  title="Open Trace Waterfall"
                                >
                                  <ExternalLink className="h-3.5 w-3.5 mr-1" />
                                  <span>Trace</span>
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
        )}

        {/* TAB 5: CROSS-SYSTEM MAPPING (TRANSACTIONAL ONLY) */}
        {isTransactional && activeTab === 'gem' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-muted-foreground pb-1">
              <span>
                Transactional cross-system identity mapping: connects source business identifiers
                with target ERP records.
              </span>
            </div>
            <div className="table-wrapper rounded-lg border border-border overflow-auto max-h-[460px]">
              <Table>
                <TableHeader className="bg-muted/70 sticky top-0 z-10">
                  <TableRow>
                    <TableHead className="text-xs font-semibold">Global Entity ID</TableHead>
                    <TableHead className="text-xs font-semibold">
                      Source Record (App &amp; ID)
                    </TableHead>
                    <TableHead className="text-xs font-semibold">
                      Destination Record (App &amp; ID)
                    </TableHead>
                    <TableHead className="text-xs font-semibold">Domain Context</TableHead>
                    <TableHead className="text-xs font-semibold">Updated At</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {gemQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        Loading cross-system mapping records...
                      </TableCell>
                    </TableRow>
                  ) : gemRows.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="text-center py-10 text-xs text-muted-foreground"
                      >
                        No identity mapping links found for this transactional stitch.
                      </TableCell>
                    </TableRow>
                  ) : (
                    gemRows.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell className="font-mono text-xs font-semibold text-foreground">
                          {row.canonicalId}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">
                            {row.sourceConnectionId}:
                          </span>{' '}
                          {row.sourceEntityId}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {row.destConnectionId ? (
                            <>
                              <span className="font-medium text-foreground">
                                {row.destConnectionId}:
                              </span>{' '}
                              {row.destEntityId ?? '—'}
                            </>
                          ) : (
                            <span className="text-muted-foreground italic">Self-Resolving</span>
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          <StatusBadge label={row.entityDomain} tone={StatusTone.NEUTRAL} />
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground font-mono">
                          {formatRelativeTimestamp(row.createdAt)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </CardContent>

      {/* Slide-out / Bottom Inspector: 3-Second Error Callout + Payload Viewer */}
      {selectedRecordDetail && (
        <div className="border-t border-border p-4 bg-muted/20 space-y-3 rounded-b-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-foreground">
                {selectedRecordDetail.title}
              </span>
              {selectedRecordDetail.statusCode !== undefined &&
                selectedRecordDetail.statusCode !== null && (
                  <StatusBadge
                    label={`HTTP ${selectedRecordDetail.statusCode}`}
                    tone={
                      selectedRecordDetail.statusCode >= 200 &&
                      selectedRecordDetail.statusCode < 300
                        ? StatusTone.HEALTHY
                        : StatusTone.CRITICAL
                    }
                  />
                )}
            </div>
            <div className="flex items-center gap-2">
              {selectedRecordDetail.isFailed && selectedRecordDetail.traceId && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={replayMutation.isPending}
                  className="h-7 px-2.5 text-xs gap-1.5 border-status-critical-border text-status-critical-fg hover:bg-status-critical-bg"
                  onClick={() => handle1ClickReplay(selectedRecordDetail.traceId!)}
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>1-Click Replay</span>
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setSelectedRecordDetail(null)}
                className="h-7 w-7 p-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* 3-Second Error Callout Banner */}
          {selectedRecordDetail.errorMessage && (
            <div className="rounded-lg border border-status-critical-border bg-status-critical-bg/25 p-3 text-xs text-status-critical-fg space-y-1">
              <div className="flex items-center justify-between font-semibold">
                <span className="flex items-center gap-1.5">
                  <AlertTriangle className="h-4 w-4" />
                  <span>
                    Failure Category: {selectedRecordDetail.failureCategory || 'DISPATCH_ERROR'}
                  </span>
                </span>
                {selectedRecordDetail.retryAfterSeconds !== null &&
                  selectedRecordDetail.retryAfterSeconds !== undefined && (
                    <span className="font-mono text-[10px]">
                      Retry-After: {selectedRecordDetail.retryAfterSeconds}s
                    </span>
                  )}
              </div>
              <div className="font-mono text-xs break-all">{selectedRecordDetail.errorMessage}</div>
            </div>
          )}

          <div className="h-64 rounded-md border border-border overflow-hidden">
            <MonacoCodeViewer value={selectedRecordDetail.payloadJson} language="json" />
          </div>
        </div>
      )}
    </Card>
  );
}
