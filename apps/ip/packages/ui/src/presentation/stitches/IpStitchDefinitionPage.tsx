import { Button, CopyableIdPill, Skeleton, StatusBadge } from '@soopa/ui';
import {
  ArrowLeft,
  CheckCircle2,
  Database,
  ExternalLink,
  History,
  Network,
  PlayCircle,
  Send,
  Sparkles,
} from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';
import {
  useNormalizedRecordsQuery,
  useOutboundRecordsQuery,
} from '../../application/use-record-queries';
import {
  useStitchDefinitionQuery,
  useStitchesQuery,
  useStitchRunsQuery,
} from '../../application/use-stitch-queries';
import type { Stitch, StitchRun } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { deriveFriendlyEntityName } from '../records/DataExplorer';
import { RecordsTable } from '../records/RecordsTable';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import { StitchExecutionsTable } from './StitchExecutionsTable';
import { DispatchCanonicalEventModal } from './StitchModals';
import { VisualStitchPipeline } from './VisualStitchPipeline';

export type StitchPageTab = 'canvas' | 'executions' | 'data';

export interface IpStitchDefinitionPageProps {
  readonly workflowId: string;
  readonly initialTraceId?: string;
  readonly initialRunId?: string;
  readonly initialTab?: StitchPageTab;
}

export function IpStitchDefinitionPage({
  workflowId,
  initialTraceId,
  initialRunId,
  initialTab,
}: IpStitchDefinitionPageProps) {
  const { navigation } = useIpWorkspace();
  const [activeMainTab, setActiveMainTab] = useState<StitchPageTab>(initialTab ?? 'canvas');
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [dispatchOpen, setDispatchOpen] = useState(false);

  // Queries
  const defView = useStitchDefinitionQuery(workflowId);
  const stitchesView = useStitchesQuery();
  const runsQuery = useStitchRunsQuery({ workflowId });
  const traceRunsQuery = useStitchRunsQuery(
    initialTraceId ? { traceId: initialTraceId } : undefined,
  );
  const normalizedQuery = useNormalizedRecordsQuery({ limit: 100 });
  const outboundQuery = useOutboundRecordsQuery({ limit: 100 });

  const definition = defView.data;
  const stitches = stitchesView.data ?? [];

  // Match the stitch associated with this workflowId
  const currentStitch = useMemo<Stitch | undefined>(() => {
    return stitches.find((s) => s.workflowId === workflowId);
  }, [stitches, workflowId]);

  // Combine runs from workflow query and trace query
  const allRuns = useMemo<readonly StitchRun[]>(() => {
    const byId = new Map<string, StitchRun>();
    for (const r of runsQuery.data ?? []) {
      byId.set(r.runId, r);
    }
    for (const r of traceRunsQuery.data ?? []) {
      if (r.workflowId === workflowId) {
        byId.set(r.runId, r);
      }
    }
    return Array.from(byId.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
  }, [runsQuery.data, traceRunsQuery.data, workflowId]);

  // Auto-select matched execution when initialTraceId is provided
  useEffect(() => {
    if (initialTraceId && !selectedRunId) {
      const match = allRuns.find((r) => r.traceId === initialTraceId);
      if (match) {
        setSelectedRunId(match.runId);
      }
    }
  }, [initialTraceId, allRuns, selectedRunId]);

  const activeRun = useMemo(
    () => allRuns.find((r) => r.runId === selectedRunId) ?? null,
    [allRuns, selectedRunId],
  );

  // Filter records strictly relevant to this stitch/workflow
  const stitchRecords = useMemo(() => {
    const allRecs = normalizedQuery.data ?? [];

    // 1. If an active run is selected, strictly scope to that execution's traceId
    if (activeRun?.traceId) {
      return allRecs.filter((r) => r.traceId === activeRun.traceId);
    }

    // 2. If no stitch definition is found and no runs exist, never leak unrelated domain records
    if (!currentStitch && allRuns.length === 0) {
      return [];
    }

    // 3. Strict relevance: records executed by this workflow or matching its canonical event type
    const workflowTraceIds = new Set(allRuns.map((r) => r.traceId));
    return allRecs.filter((r) => {
      // Direct execution provenance: processed by a run of this workflow
      if (workflowTraceIds.has(r.traceId)) return true;
      // Canonical event type contract match
      if (
        currentStitch?.canonicalEventType &&
        r.canonicalType === currentStitch.canonicalEventType
      ) {
        return true;
      }
      return false;
    });
  }, [normalizedQuery.data, currentStitch, activeRun, allRuns]);

  // Friendly entity display name for the Data tab
  const entityDisplayName = useMemo(() => {
    if (currentStitch?.canonicalEventType) {
      return deriveFriendlyEntityName(currentStitch.canonicalEventType);
    }
    return currentStitch?.name || deriveFriendlyEntityName(workflowId);
  }, [currentStitch, workflowId]);

  // If a trace executed multiple distinct stitches, allow tabbed switching at the top
  const attachedWorkflowsForTrace = useMemo(() => {
    if (!initialTraceId) return [];
    const traceRuns = traceRunsQuery.data ?? [];
    const uniqueWfs = Array.from(new Set(traceRuns.map((r) => r.workflowId)));
    return uniqueWfs.map((wfId) => {
      const st = stitches.find((s) => s.workflowId === wfId);
      const name = st?.name || wfId.replace(/^workflow[._]/i, '').replace(/[._-]/g, ' ');
      return {
        workflowId: wfId,
        name,
        isActive: wfId === workflowId,
      };
    });
  }, [initialTraceId, traceRunsQuery.data, stitches, workflowId]);

  const displayName = currentStitch?.name?.trim() || definition?.workflowId || workflowId;

  return (
    <div className="space-y-6">
      <IpPageHeader
        title={displayName}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => navigation.toStitches()}
              className="gap-1.5"
            >
              <ArrowLeft className="h-4 w-4" />
              <span>Back to Stitches</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setDispatchOpen(true)}
              className="gap-1.5"
            >
              <Send className="h-3.5 w-3.5" />
              <span>Dispatch Test Event</span>
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
              <span>Field Mapper</span>
            </Button>
          </div>
        }
      />

      <ApiProblemBanner problem={defView.problem} onRetry={() => void defView.refetch()} />

      {/* Multi-Stitch Switcher for Traces executing multiple workflows */}
      {attachedWorkflowsForTrace.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
          <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground uppercase tracking-wider mr-2">
            <Network className="h-4 w-4 text-primary" />
            <span>Trace Stitches ({attachedWorkflowsForTrace.length}):</span>
          </div>
          {attachedWorkflowsForTrace.map((item) => (
            <Button
              key={item.workflowId}
              type="button"
              variant={item.isActive ? 'default' : 'outline'}
              size="xs"
              onClick={() =>
                navigation.toStitchDefinition(item.workflowId, { traceId: initialTraceId })
              }
              className="gap-1.5 text-xs h-7"
            >
              {item.isActive && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
              <span>{item.name}</span>
            </Button>
          ))}
        </div>
      )}

      {/* Top-Level Navigation Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        <button
          type="button"
          onClick={() => setActiveMainTab('canvas')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all -mb-px ${
            activeMainTab === 'canvas'
              ? 'border-primary text-primary bg-primary/5'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
          }`}
        >
          <Network className="h-4 w-4" />
          <span>Canvas</span>
          {activeRun && (
            <span className="ml-1.5 px-1.5 py-0.2 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px]">
              Active Run
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveMainTab('executions')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all -mb-px ${
            activeMainTab === 'executions'
              ? 'border-primary text-primary bg-primary/5'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
          }`}
        >
          <History className="h-4 w-4" />
          <span>Executions</span>
          <span className="ml-1 px-1.5 py-0.2 rounded-full bg-muted text-muted-foreground font-mono text-[10px]">
            {allRuns.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveMainTab('data')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all -mb-px ${
            activeMainTab === 'data'
              ? 'border-primary text-primary bg-primary/5'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
          }`}
        >
          <Database className="h-4 w-4" />
          <span>Data</span>
          {stitchRecords.length > 0 && (
            <span className="ml-1 px-1.5 py-0.2 rounded-full bg-muted text-muted-foreground font-mono text-[10px]">
              {stitchRecords.length}
            </span>
          )}
        </button>
      </div>

      {defView.isLoading || !definition ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          {/* TAB 1: CANVAS (DAG) */}
          {activeMainTab === 'canvas' && (
            <div className="space-y-4">
              {/* Overlay Execution Toolbar */}
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl border border-border bg-card text-xs">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Overlay Run:
                  </span>
                  <select
                    value={selectedRunId ?? ''}
                    onChange={(e) => setSelectedRunId(e.target.value ? e.target.value : null)}
                    className="h-8 rounded-lg border border-border bg-background px-3 text-xs font-mono font-medium focus:ring-1 focus:ring-primary"
                  >
                    <option value="">Blueprint (No Run Selected)</option>
                    {allRuns.map((r) => (
                      <option key={r.runId} value={r.runId}>
                        {r.runId} ({r.status}) · {formatRelativeTimestamp(r.createdAt)}
                      </option>
                    ))}
                  </select>

                  {activeRun && (
                    <div className="flex items-center gap-2">
                      <StatusBadge
                        label={activeRun.status}
                        tone={mapStitchRunStatusTone(activeRun.status)}
                      />
                      <span className="text-muted-foreground font-mono text-xs">
                        ({activeRun.steps.filter((s) => s.status === 'COMPLETED').length}/
                        {activeRun.steps.length} steps live on DAG)
                      </span>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {activeRun ? (
                    <>
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        onClick={() => setSelectedRunId(null)}
                        className="h-7 text-xs text-muted-foreground hover:text-foreground"
                      >
                        Reset to Blueprint
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
                        onClick={() => navigation.toTraceDetail(activeRun.traceId)}
                        className="h-7 text-xs gap-1"
                      >
                        <span>Trace Waterfall</span>
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="xs"
                        onClick={() => setActiveMainTab('data')}
                        className="h-7 text-xs gap-1"
                      >
                        <Database className="h-3 w-3" />
                        <span>View Data</span>
                      </Button>
                    </>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() => setActiveMainTab('executions')}
                      className="h-7 text-xs gap-1"
                    >
                      <History className="h-3 w-3" />
                      <span>View All Executions ({allRuns.length})</span>
                    </Button>
                  )}
                </div>
              </div>

              {/* Contextual Scoped Node Banner */}
              {selectedNodeKey && (
                <div className="flex items-center justify-between px-3.5 py-2 rounded-xl bg-primary/10 border border-primary/25 text-xs">
                  <span className="flex items-center gap-2 text-foreground font-medium">
                    <span>🔍 Scoped to DAG Node:</span>
                    <code className="font-mono font-semibold bg-background px-2 py-0.5 rounded border border-border">
                      {selectedNodeKey}
                    </code>
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => setSelectedNodeKey(null)}
                      className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
                    >
                      Clear Lens
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="xs"
                      onClick={() => setActiveMainTab('data')}
                      className="h-6 px-2 text-xs gap-1"
                    >
                      <Database className="h-3 w-3" />
                      <span>Inspect Stage Data</span>
                    </Button>
                  </div>
                </div>
              )}

              {/* Full-Height Visual DAG Pipeline */}
              <VisualStitchPipeline
                stitch={currentStitch}
                definition={definition}
                stepRuns={activeRun?.steps}
                selectedNodeKey={selectedNodeKey}
                onSelectNode={setSelectedNodeKey}
                onResetSelection={() => setSelectedNodeKey(null)}
                onSelectStage={() => setActiveMainTab('data')}
              />
            </div>
          )}

          {/* TAB 2: EXECUTIONS */}
          {activeMainTab === 'executions' && (
            <div className="space-y-4">
              <StitchExecutionsTable
                runs={allRuns}
                activeRunId={selectedRunId}
                isLoading={runsQuery.isLoading || traceRunsQuery.isLoading}
                onSelectRunId={setSelectedRunId}
                onInspectOnDag={(runId) => {
                  setSelectedRunId(runId);
                  setActiveMainTab('canvas');
                }}
                onOpenTrace={navigation.toTraceDetail}
                onOpenData={(traceId) => {
                  const match = allRuns.find((r) => r.traceId === traceId);
                  if (match) setSelectedRunId(match.runId);
                  setActiveMainTab('data');
                }}
              />
            </div>
          )}

          {/* TAB 3: DATA (Exact same Data Explorer UI with zero duplication) */}
          {activeMainTab === 'data' && (
            <div className="space-y-4">
              {activeRun && (
                <div className="flex items-center justify-between px-3.5 py-2 rounded-xl bg-primary/10 border border-primary/20 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-primary">Scoped to Execution:</span>
                    <CopyableIdPill value={activeRun.runId} prefixLabel="Run" truncateLength={16} />
                    <span className="text-muted-foreground font-mono">· Trace:</span>
                    <CopyableIdPill value={activeRun.traceId} truncateLength={16} />
                    <span className="text-muted-foreground">({stitchRecords.length} records)</span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() => setSelectedRunId(null)}
                    className="h-6 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Show All Workflow Records
                  </Button>
                </div>
              )}

              {stitchRecords.length === 0 && !normalizedQuery.isLoading ? (
                <div className="rounded-xl border border-dashed border-border p-12 text-center bg-card/50">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-muted/60 text-muted-foreground mb-3">
                    <Database className="h-6 w-6" />
                  </div>
                  <h4 className="text-sm font-semibold text-foreground">
                    No {entityDisplayName.toLowerCase()} found for this workflow
                  </h4>
                  <p className="mt-1 text-xs text-muted-foreground max-w-md mx-auto">
                    {activeRun
                      ? `Execution run ${activeRun.runId} did not produce or normalize any ${entityDisplayName.toLowerCase()} records.`
                      : `When events for ${displayName} are executed, synchronized ${entityDisplayName.toLowerCase()} records will appear here.`}
                  </p>
                  <div className="mt-4 flex items-center justify-center gap-3">
                    {activeRun && (
                      <Button
                        type="button"
                        variant="secondary"
                        size="xs"
                        onClick={() => setSelectedRunId(null)}
                      >
                        View All Workflow Records
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="default"
                      size="xs"
                      onClick={() => setDispatchOpen(true)}
                      className="gap-1.5"
                    >
                      <Send className="h-3.5 w-3.5" />
                      <span>Dispatch Test Event</span>
                    </Button>
                  </div>
                </div>
              ) : (
                /* Reuses the exact same canonical business records table */
                <RecordsTable
                  entityName={entityDisplayName}
                  records={stitchRecords}
                  isLoading={normalizedQuery.isLoading}
                  outboundRecords={outboundQuery.data ?? []}
                  onOpenTraceDetail={navigation.toTraceDetail}
                  onOpenTraceStitches={(trcId) =>
                    navigation.toStitchDefinition(workflowId, { traceId: trcId, tab: 'canvas' })
                  }
                />
              )}
            </div>
          )}
        </>
      )}

      <DispatchCanonicalEventModal
        open={dispatchOpen}
        onOpenChange={setDispatchOpen}
        onOpenRun={(runId) => navigation.toStitchRun(runId)}
        defaultCanonicalEventType={currentStitch?.canonicalEventType}
      />
    </div>
  );
}
