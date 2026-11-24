import {
  Button,
  Card,
  CopyableIdPill,
  StatusBadge,
  StatusTone,
  type StatusToneValue,
} from '@soopa/ui';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  Layers,
  Network,
  RefreshCw,
  Send,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import {
  useStitchDefinitionsQuery,
  useStitchesQuery,
  useStitchRunsQuery,
} from '../../application/use-stitch-queries';
import { useIpTraceQuery } from '../../application/use-trace-queries';
import type { Stitch, StitchDefinition, StitchRun, StitchStepRun } from '../../domain/stitch';
import type { OutboundRecord } from '../../domain/trace';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import { VisualStitchPipeline } from '../stitches/VisualStitchPipeline';

export interface IpTraceStitchesPageProps {
  readonly traceId: string;
  readonly initialWorkflowId?: string;
  readonly onBack?: () => void;
  readonly onOpenTraceWaterfall?: (traceId: string) => void;
  readonly onOpenStitchRun?: (runId: string) => void;
  readonly onOpenStitchDefinition?: (workflowId: string) => void;
}

interface AttachedStitchTabItem {
  readonly id: string;
  readonly label: string;
  readonly workflowId: string;
  readonly workflowVersion: number;
  readonly status: string;
  readonly tone: StatusToneValue;
  readonly run?: StitchRun | null;
  readonly definition?: StitchDefinition | null;
  readonly stitch?: Stitch | null;
  readonly outbound?: OutboundRecord | null;
}

export function IpTraceStitchesPage({
  traceId,
  initialWorkflowId,
  onBack,
  onOpenTraceWaterfall,
  onOpenStitchRun,
  onOpenStitchDefinition,
}: IpTraceStitchesPageProps) {
  const { navigation } = useIpWorkspace();
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [copiedPayload, setCopiedPayload] = useState<string | null>(null);

  // 1. Data queries
  const traceQuery = useIpTraceQuery(traceId);
  const trace = traceQuery.data;

  const runsQuery = useStitchRunsQuery({ traceId });
  const runs = runsQuery.data ?? [];

  const definitionsQuery = useStitchDefinitionsQuery();
  const allDefinitions = definitionsQuery.data ?? [];

  const stitchesQuery = useStitchesQuery();
  const allStitches = stitchesQuery.data ?? [];

  const outboundRecords = trace?.outboundRecords ?? [];

  // 2. Data-driven attached stitches calculation (Zero hardcoding)
  const attachedStitches = useMemo<readonly AttachedStitchTabItem[]>(() => {
    // A. If durable workflow runs exist for this trace
    if (runs.length > 0) {
      return runs.map((run) => {
        const def =
          allDefinitions.find(
            (d) => d.workflowId === run.workflowId && d.version === run.workflowVersion,
          ) ??
          allDefinitions.find((d) => d.workflowId === run.workflowId) ??
          null;

        const stitch = allStitches.find((s) => s.workflowId === run.workflowId) ?? null;

        // Correlate with outbound record if present
        const outbound =
          outboundRecords.find(
            (o) =>
              o.appId.toLowerCase() === run.workflowId.toLowerCase() ||
              run.workflowId.toLowerCase().includes(o.appId.toLowerCase()) ||
              o.traceId === run.traceId,
          ) ??
          outboundRecords[0] ??
          null;

        const tone = mapStitchRunStatusTone(run.status);
        const name =
          stitch?.name ||
          run.workflowId
            .replace(/^workflow[._]/i, '')
            .replace(/[._-]/g, ' ')
            .replace(/\b\w/g, (c) => c.toUpperCase());

        return {
          id: run.runId,
          label: `${name} Stitch`,
          workflowId: run.workflowId,
          workflowVersion: run.workflowVersion,
          status: run.status,
          tone,
          run,
          definition: def,
          stitch,
          outbound,
        };
      });
    }

    // B. Fallback: Outbound deliveries executed without separate durable runs
    if (outboundRecords.length > 0) {
      return outboundRecords.map((out, idx) => {
        const appName = out.appId.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        const isFailed =
          out.status === 'FAILED' ||
          (out.responseStatusCode != null && out.responseStatusCode >= 400);
        const isDelivered = out.status === 'DELIVERED' || out.responseStatusCode === 200;
        const tone = isFailed
          ? StatusTone.CRITICAL
          : isDelivered
            ? StatusTone.HEALTHY
            : StatusTone.NEUTRAL;

        return {
          id: out.id || `outbound_${idx}`,
          label: `${appName} Delivery`,
          workflowId: out.appId,
          workflowVersion: 1,
          status: isFailed ? `FAILED (${out.responseStatusCode ?? 503})` : out.status,
          tone,
          run: null,
          definition: null,
          stitch: null,
          outbound: out,
        };
      });
    }

    return [];
  }, [runs, allDefinitions, allStitches, outboundRecords]);

  // Resolve active tab
  const resolvedActiveTabId =
    activeTabId && attachedStitches.some((s) => s.id === activeTabId)
      ? activeTabId
      : initialWorkflowId
        ? (attachedStitches.find((s) => s.workflowId === initialWorkflowId)?.id ??
          attachedStitches[0]?.id ??
          null)
        : (attachedStitches[0]?.id ?? null);

  const currentTab =
    attachedStitches.find((s) => s.id === resolvedActiveTabId) ?? attachedStitches[0] ?? null;

  // Extract business record metadata from trace if available
  const normRecord = trace?.normalizedRecords?.[0] ?? null;
  const rawData = (normRecord?.canonicalData ?? {}) as Record<string, unknown>;
  const docIdentifier =
    rawData.invoiceNumber ||
    rawData.invoice_number ||
    rawData.orderNumber ||
    rawData.order_number ||
    rawData.documentNumber ||
    rawData.id ||
    normRecord?.sourceId;

  const entityType = normRecord?.canonicalType
    ? normRecord.canonicalType.replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    : 'Business Entity';

  const customerName =
    typeof rawData.customerName === 'string'
      ? rawData.customerName
      : typeof rawData.customer === 'string'
        ? rawData.customer
        : null;

  const totalAmount =
    typeof rawData.total === 'number'
      ? rawData.total
      : typeof rawData.total_amount === 'number'
        ? rawData.total_amount
        : null;

  const currency = typeof rawData.currency === 'string' ? rawData.currency.toUpperCase() : 'USD';

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPayload(label);
    setTimeout(() => setCopiedPayload(null), 2000);
  };

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else if (window.history.length > 1) {
      window.history.back();
    } else {
      navigation.toCommandCenter();
    }
  };

  const handleOpenWaterfall = () => {
    if (onOpenTraceWaterfall) {
      onOpenTraceWaterfall(traceId);
    } else {
      navigation.toTraceDetail(traceId);
    }
  };

  const isLoading =
    (traceQuery.isLoading && !trace) || (runsQuery.isLoading && runs.length === 0 && !trace);

  return (
    <div className="space-y-4 p-4 max-w-7xl mx-auto">
      {/* ── 1. Pinned Business Context Header Bar ─────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl border border-border bg-card shadow-xs">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleBack}
            className="gap-1.5 text-xs text-muted-foreground hover:text-foreground h-8 px-2.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Records</span>
          </Button>

          <div className="h-4 w-px bg-border/60 hidden sm:block" />

          <div className="flex flex-wrap items-center gap-2 text-xs">
            {docIdentifier ? (
              <span className="font-bold text-foreground">
                {entityType} #{String(docIdentifier)}
              </span>
            ) : (
              <span className="font-bold text-foreground">Trace Workflows</span>
            )}

            {customerName && <span className="text-muted-foreground">· {customerName}</span>}

            {totalAmount !== null && (
              <span className="font-mono font-semibold text-foreground">
                · ${totalAmount.toFixed(2)} {currency}
              </span>
            )}

            <span className="text-muted-foreground font-mono">· Trace:</span>
            <CopyableIdPill value={traceId} truncateLength={16} />
          </div>
        </div>

        <div className="flex items-center gap-2">
          {trace && (
            <StatusBadge
              label={trace.status}
              tone={
                trace.status === 'SUCCEEDED'
                  ? StatusTone.HEALTHY
                  : trace.status === 'FAILED'
                    ? StatusTone.CRITICAL
                    : StatusTone.WARNING
              }
            />
          )}

          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={handleOpenWaterfall}
            className="gap-1.5 text-xs h-8 px-3"
          >
            <span>Full Trace Waterfall</span>
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
      </div>

      {/* ── 2. Pure Data-Driven Stitch Tabs Bar ──────────────────── */}
      {attachedStitches.length > 0 ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
            <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground uppercase tracking-wider mr-2">
              <Network className="h-4 w-4 text-primary" />
              <span>Stitches ({attachedStitches.length}):</span>
            </div>

            {attachedStitches.map((item) => {
              const isActive = item.id === currentTab?.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setActiveTabId(item.id);
                    setSelectedNodeKey(null);
                  }}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                    isActive
                      ? 'bg-card border-primary text-foreground shadow-xs ring-1 ring-primary/20'
                      : 'bg-muted/40 border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/70'
                  }`}
                >
                  {item.tone === StatusTone.CRITICAL ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-destructive shrink-0" />
                  ) : item.tone === StatusTone.HEALTHY ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  ) : (
                    <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  )}
                  <span>{item.label}</span>
                  <StatusBadge label={item.status} tone={item.tone} />
                </button>
              );
            })}
          </div>

          {/* ── 3. Active Stitch DAG Canvas View ─────────────────────── */}
          {currentTab && (
            <div className="space-y-4">
              {/* Stitch Sub-Header Bar */}
              <Card className="p-4 border border-border bg-card">
                <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border/60">
                  <div className="flex items-center gap-2.5">
                    <div className="p-2 rounded-xl bg-primary/10 text-primary">
                      <Layers className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-base font-bold text-foreground">{currentTab.label}</h2>
                        <StatusBadge label={currentTab.status} tone={currentTab.tone} />
                      </div>
                      <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-2 mt-0.5">
                        <span className="font-mono">
                          Workflow: {currentTab.workflowId}:v{currentTab.workflowVersion}
                        </span>
                        {currentTab.run && (
                          <>
                            <span>·</span>
                            <span>Run ID:</span>
                            <CopyableIdPill value={currentTab.run.runId} truncateLength={16} />
                          </>
                        )}
                        {currentTab.run?.finishedAt && (
                          <>
                            <span>·</span>
                            <span>
                              Completed {formatRelativeTimestamp(currentTab.run.finishedAt)}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  {currentTab.run && onOpenStitchRun && (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() => onOpenStitchRun(currentTab.run!.runId)}
                      className="gap-1.5 text-xs h-7 px-2.5"
                    >
                      <span>Inspect Execution Run</span>
                      <ExternalLink className="h-3 w-3 text-muted-foreground" />
                    </Button>
                  )}
                </div>

                {/* Error Banner if Stitch Failed */}
                {currentTab.run?.failureCode && (
                  <div className="mt-3 p-3 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-xs space-y-1">
                    <div className="font-bold flex items-center gap-1.5">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      <span>Workflow Execution Failed ({currentTab.run.failureCode})</span>
                    </div>
                    {currentTab.run.failureDetail && (
                      <div className="font-mono text-[11px] break-words pl-5">
                        {currentTab.run.failureDetail}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Visual Interactive DAG Canvas ── */}
                <div className="mt-4 rounded-xl border border-border bg-muted/10 overflow-hidden">
                  <VisualStitchPipeline
                    stitch={currentTab.stitch}
                    definition={
                      currentTab.definition ?? {
                        workflowId: currentTab.workflowId,
                        version: currentTab.workflowVersion,
                        defaultPriority: 'DEFAULT',
                        description: currentTab.label,
                        nodes: [
                          {
                            nodeKey: 'intake',
                            kind: 'TASK',
                            stepType: 'intake',
                            parents: [],
                            edgeCondition: 'TRUE',
                            effectPolicy: 'IDEMPOTENT',
                            waitEventKey: null,
                            queueName: 'default',
                          },
                          {
                            nodeKey: 'dispatch',
                            kind: 'TASK',
                            stepType: 'dispatch',
                            parents: ['intake'],
                            edgeCondition: 'ON_SUCCESS',
                            effectPolicy: 'TRANSACTIONAL',
                            waitEventKey: null,
                            queueName: 'default',
                          },
                        ],
                      }
                    }
                    stepRuns={currentTab.run?.steps ?? []}
                    selectedNodeKey={selectedNodeKey}
                    onSelectNode={setSelectedNodeKey}
                  />
                </div>
              </Card>

              {/* ── 4. Outbound Wire Delivery Inspection (If present) ── */}
              {currentTab.outbound && (
                <Card className="p-4 border border-border bg-card space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-border/50">
                    <div className="flex items-center gap-2">
                      <Send className="h-4 w-4 text-primary" />
                      <span className="text-xs font-bold text-foreground">
                        Target System Delivery ({currentTab.outbound.appId.toUpperCase()})
                      </span>
                      <StatusBadge
                        label={
                          currentTab.outbound.responseStatusCode
                            ? `${currentTab.outbound.responseStatusCode} ${currentTab.outbound.status}`
                            : currentTab.outbound.status
                        }
                        tone={
                          currentTab.outbound.status === 'DELIVERED' ||
                          currentTab.outbound.responseStatusCode === 200
                            ? StatusTone.HEALTHY
                            : StatusTone.CRITICAL
                        }
                      />
                    </div>
                    {currentTab.outbound.sentAt && (
                      <span className="text-xs font-mono text-muted-foreground">
                        Sent {formatRelativeTimestamp(currentTab.outbound.sentAt)}
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 p-2.5 rounded-lg bg-muted/20 border border-border/50 text-xs">
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase">
                        Target Endpoint
                      </span>
                      <div className="font-mono text-[11px] text-foreground mt-0.5 truncate">
                        {currentTab.outbound.httpMethod} {currentTab.outbound.targetUrl}
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase">Latency</span>
                      <div className="font-mono text-foreground mt-0.5">
                        {currentTab.outbound.durationMs != null
                          ? `${currentTab.outbound.durationMs}ms`
                          : '—'}
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase">
                        External Record ID
                      </span>
                      <div className="font-mono text-foreground mt-0.5">
                        {currentTab.outbound.externalRecordId || '—'}
                      </div>
                    </div>
                  </div>

                  {currentTab.outbound.errorMessage && (
                    <div className="p-2.5 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs space-y-1">
                      <span className="font-bold">Delivery Error:</span>
                      <div className="font-mono text-[11px] break-words">
                        {currentTab.outbound.errorMessage}
                      </div>
                    </div>
                  )}

                  {/* Wire Payloads */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 pt-1">
                    {currentTab.outbound.requestBody && (
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wide">
                            Request
                          </span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="xs"
                            onClick={() =>
                              handleCopy(
                                JSON.stringify(currentTab.outbound!.requestBody, null, 2),
                                'request',
                              )
                            }
                            className="gap-1 text-xs h-5 px-2"
                          >
                            <Copy className="h-3 w-3" />
                            <span>{copiedPayload === 'request' ? 'Copied' : 'Copy'}</span>
                          </Button>
                        </div>
                        <pre className="text-xs font-mono bg-muted/30 p-3 rounded-lg border border-border/60 text-foreground overflow-x-auto leading-relaxed max-h-64">
                          {JSON.stringify(currentTab.outbound.requestBody, null, 2)}
                        </pre>
                      </div>
                    )}

                    {currentTab.outbound.responseBody && (
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wide">
                            Response
                          </span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="xs"
                            onClick={() =>
                              handleCopy(
                                JSON.stringify(currentTab.outbound!.responseBody, null, 2),
                                'response',
                              )
                            }
                            className="gap-1 text-xs h-5 px-2"
                          >
                            <Copy className="h-3 w-3" />
                            <span>{copiedPayload === 'response' ? 'Copied' : 'Copy'}</span>
                          </Button>
                        </div>
                        <pre className="text-xs font-mono bg-muted/30 p-3 rounded-lg border border-border/60 text-foreground overflow-x-auto leading-relaxed max-h-64">
                          {JSON.stringify(currentTab.outbound.responseBody, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </Card>
              )}
            </div>
          )}
        </div>
      ) : isLoading ? (
        <Card className="p-12 text-center text-sm text-muted-foreground flex flex-col items-center justify-center gap-3">
          <RefreshCw className="h-5 w-5 animate-spin text-primary" />
          <span>Loading attached workflow stitches for trace {traceId}...</span>
        </Card>
      ) : (
        <Card className="p-12 text-center text-sm text-muted-foreground space-y-2">
          <Network className="h-8 w-8 text-muted-foreground mx-auto" />
          <h3 className="text-base font-semibold text-foreground">No Workflow Stitches Attached</h3>
          <p className="max-w-md mx-auto text-xs">
            No durable workflow runs or outbound dispatches are recorded for trace{' '}
            <span className="font-mono text-foreground font-semibold">{traceId}</span>.
          </p>
          <div className="pt-2">
            <Button type="button" variant="outline" size="sm" onClick={handleBack}>
              Return to Data Explorer
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
