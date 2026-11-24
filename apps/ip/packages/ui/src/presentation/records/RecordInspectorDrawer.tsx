import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  MonacoCodeViewer,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
  FileCode2,
  History,
  Layers,
  Radio,
  RotateCcw,
  Send,
  X,
} from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import { useIpTraceQuery, useReplayTransactionMutation } from '../../application/use-trace-queries';
import { ReplayStage } from '../../domain/enums';
import type { NormalizedRecord } from '../../domain/trace';
import {
  formatBytesCompact,
  formatRelativeTimestamp,
  stringifyJsonPretty,
} from '../shared/status-mapping';

export interface RecordInspectorDrawerProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly record: NormalizedRecord | null;
  readonly entityDisplayName?: string;
  readonly onOpenTraces?: (traceId: string) => void;
}

export function RecordInspectorDrawer({
  isOpen,
  onClose,
  record,
  entityDisplayName = 'Record',
  onOpenTraces,
}: RecordInspectorDrawerProps) {
  const [activeTab, setActiveTab] = useState<string>('business');

  // Query the aggregate trace for full 360° lifecycle inspection
  const traceQuery = useIpTraceQuery(record?.traceId ?? '', Boolean(isOpen && record?.traceId));
  const replayMutation = useReplayTransactionMutation();

  if (!record) return null;

  const trace = traceQuery.data;
  const outboundRecord = trace?.outboundRecords?.[0] ?? null;
  const inboundRecord = trace?.inboundRecord ?? null;
  const replicaRecord = trace?.replicaRecords?.[0] ?? null;
  const gemMappings = trace?.entityMappings ?? [];
  const traceEvents = trace?.traceEvents ?? [];

  // Determine delivery status
  const isOutboundFailed =
    outboundRecord &&
    (outboundRecord.status === 'FAILED' ||
      (outboundRecord.responseStatusCode !== null && outboundRecord.responseStatusCode >= 400));
  const isOutboundDelivered =
    outboundRecord &&
    (outboundRecord.status === 'DELIVERED' || outboundRecord.responseStatusCode === 200);

  const handleReplay = () => {
    if (!record.traceId) return;
    replayMutation.mutate(
      { traceId: record.traceId, stage: ReplayStage.RETRY_DELIVER },
      {
        onSuccess: (res) => {
          if (res.ok) {
            toast.success('Replay delivery initiated. Inspecting new execution status...');
            void traceQuery.refetch();
          } else {
            toast.error(`Replay failed: ${res.error.message}`);
          }
        },
      },
    );
  };

  const canonicalData =
    record.canonicalData && typeof record.canonicalData === 'object'
      ? (record.canonicalData as Record<string, unknown>)
      : {};

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-2xl border-l border-border bg-background p-0 shadow-2xl flex flex-col h-full overflow-hidden"
      >
        {/* Header */}
        <div className="p-5 border-b border-border bg-card/80 backdrop-blur-sm flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {entityDisplayName} Inspection
              </span>
              {isOutboundFailed && (
                <StatusBadge label="503 DELIVERY FAILED" tone={StatusTone.CRITICAL} />
              )}
              {isOutboundDelivered && <StatusBadge label="DELIVERED" tone={StatusTone.HEALTHY} />}
            </div>
            <SheetTitle className="text-lg font-bold text-foreground flex items-center gap-2">
              <span>{record.sourceId}</span>
              <CopyableIdPill value={record.sourceId} truncateLength={16} />
            </SheetTitle>
            <SheetDescription className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
              <span>
                Trace: <span className="font-mono">{record.traceId}</span> · Updated{' '}
                {formatRelativeTimestamp(record.normalizedAt)}
              </span>
              {onOpenTraces && (
                <button
                  type="button"
                  onClick={() => onOpenTraces(record.traceId)}
                  className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline font-medium"
                >
                  <ExternalLink className="h-3 w-3" />
                  <span>Open Full Trace</span>
                </button>
              )}
            </SheetDescription>
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="h-8 w-8 p-0 rounded-lg text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Tab Navigation */}
        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex-1 flex flex-col overflow-hidden"
        >
          <div className="px-5 pt-3 pb-2 border-b border-border bg-muted/30">
            <TabsList className="bg-muted/60 p-0.5 w-full justify-start overflow-x-auto">
              <TabsTrigger value="business" className="text-xs gap-1.5">
                <Database className="h-3.5 w-3.5" />
                <span>Record Data</span>
              </TabsTrigger>
              <TabsTrigger value="outbound" className="text-xs gap-1.5 relative">
                <Send className="h-3.5 w-3.5" />
                <span>Outbound</span>
                {isOutboundFailed && (
                  <span className="h-2 w-2 rounded-full bg-status-critical-fg animate-pulse" />
                )}
              </TabsTrigger>
              <TabsTrigger value="inbound" className="text-xs gap-1.5">
                <Radio className="h-3.5 w-3.5" />
                <span>Inbound</span>
              </TabsTrigger>
              <TabsTrigger value="replica" className="text-xs gap-1.5">
                <Layers className="h-3.5 w-3.5" />
                <span>Replica</span>
              </TabsTrigger>
              <TabsTrigger value="mappings" className="text-xs gap-1.5">
                <ArrowRightLeft className="h-3.5 w-3.5" />
                <span>Identity Mappings</span>
              </TabsTrigger>
              <TabsTrigger value="lifecycle" className="text-xs gap-1.5">
                <History className="h-3.5 w-3.5" />
                <span>Lifecycle</span>
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {/* ── TAB 1: Business Record Data ───────────────────────────────── */}
            <TabsContent value="business" className="m-0 space-y-4">
              <Card className="border border-border bg-card">
                <CardHeader className="p-4 pb-2">
                  <CardTitle className="text-sm font-semibold flex items-center justify-between">
                    <span>Business Attributes</span>
                    <CopyableIdPill value={record.id} prefixLabel="Record ID" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 pt-2">
                  <div className="grid grid-cols-2 gap-3">
                    {Object.entries(canonicalData).map(([key, val]) => (
                      <div
                        key={key}
                        className="p-2.5 rounded-lg border border-border/60 bg-muted/20"
                      >
                        <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                          {key.replace(/([A-Z])/g, ' $1').replace(/[._]/g, ' ')}
                        </div>
                        <div className="text-sm font-semibold text-foreground mt-0.5 truncate">
                          {val !== null && typeof val === 'object'
                            ? JSON.stringify(val)
                            : String(val ?? '—')}
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Collapsible raw JSON */}
              <div className="space-y-2">
                <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                  <FileCode2 className="h-3.5 w-3.5" />
                  <span>Payload Representation (JSON)</span>
                </div>
                <div className="rounded-xl border border-border overflow-hidden">
                  <MonacoCodeViewer
                    height={220}
                    value={stringifyJsonPretty(record.canonicalData)}
                  />
                </div>
              </div>
            </TabsContent>

            {/* ── TAB 2: Target Delivery (Outbound) ─────────────────────────── */}
            <TabsContent value="outbound" className="m-0 space-y-4">
              {outboundRecord ? (
                <>
                  {isOutboundFailed && (
                    <Card className="border-status-critical-border bg-status-critical-bg/20">
                      <CardContent className="p-4 space-y-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5">
                            <AlertTriangle className="h-5 w-5 text-status-critical-fg mt-0.5 shrink-0" />
                            <div>
                              <div className="font-semibold text-sm text-status-critical-fg">
                                Delivery Error (HTTP {outboundRecord.responseStatusCode ?? 500})
                              </div>
                              <p className="text-xs text-foreground/80 mt-1 font-mono">
                                {outboundRecord.errorMessage ||
                                  'Delivery failed on target system HTTP transmission.'}
                              </p>
                              {outboundRecord.retryAfterSeconds && (
                                <div className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  <span>
                                    Retry backoff recommendation:{' '}
                                    <strong>{outboundRecord.retryAfterSeconds}s</strong>
                                  </span>
                                </div>
                              )}
                            </div>
                          </div>

                          <Button
                            type="button"
                            size="sm"
                            onClick={handleReplay}
                            disabled={replayMutation.isPending}
                            className="shrink-0 gap-1.5 bg-status-critical-fg text-white hover:bg-status-critical-fg/90"
                          >
                            <RotateCcw
                              className={`h-3.5 w-3.5 ${replayMutation.isPending ? 'animate-spin' : ''}`}
                            />
                            <span>
                              {replayMutation.isPending ? 'Replaying...' : 'Replay Delivery'}
                            </span>
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {isOutboundDelivered && (
                    <Card className="border-status-healthy-border bg-status-healthy-bg/20">
                      <CardContent className="p-4 flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          <CheckCircle2 className="h-5 w-5 text-status-healthy-fg shrink-0" />
                          <div>
                            <div className="font-semibold text-sm text-status-healthy-fg">
                              Delivered Successfully (HTTP {outboundRecord.responseStatusCode})
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              Receipt confirmed by target system at{' '}
                              {formatRelativeTimestamp(outboundRecord.sentAt)}
                            </div>
                          </div>
                        </div>
                        <StatusBadge label="200 OK" tone={StatusTone.HEALTHY} />
                      </CardContent>
                    </Card>
                  )}

                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Target System &amp; Method
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block truncate">
                        {outboundRecord.httpMethod} {outboundRecord.targetUrl}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Duration &amp; Attempt
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block">
                        {outboundRecord.durationMs ? `${outboundRecord.durationMs}ms` : '—'} ·
                        Attempt {outboundRecord.attemptNumber}
                      </span>
                    </div>
                  </div>

                  {/* Outbound Response Payload */}
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground">Response</div>
                    <div className="rounded-xl border border-border overflow-hidden">
                      <MonacoCodeViewer
                        height={180}
                        value={stringifyJsonPretty(outboundRecord.responseBody)}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-xl border border-dashed border-border">
                  No outbound transmission record recorded yet for this event.
                </div>
              )}
            </TabsContent>

            {/* ── TAB 3: Source Wire (Inbound) ──────────────────────────────── */}
            <TabsContent value="inbound" className="m-0 space-y-4">
              {inboundRecord ? (
                <>
                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Ingestion Mode
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block">
                        {inboundRecord.ingestionMode}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Response Status
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block">
                        HTTP {inboundRecord.responseStatusCode ?? 200} Accepted
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Payload Size &amp; Time
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block">
                        {formatBytesCompact(inboundRecord.requestSizeBytes)} ·{' '}
                        {inboundRecord.durationMs ? `${inboundRecord.durationMs}ms` : '—'}
                      </span>
                    </div>
                  </div>

                  {/* Headers */}
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground">
                      Request Headers
                    </div>
                    <div className="rounded-xl border border-border overflow-hidden">
                      <MonacoCodeViewer
                        height={120}
                        value={stringifyJsonPretty(inboundRecord.requestHeaders)}
                      />
                    </div>
                  </div>

                  {/* Wire Body */}
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground">Request</div>
                    <div className="rounded-xl border border-border overflow-hidden">
                      <MonacoCodeViewer
                        height={200}
                        value={stringifyJsonPretty(inboundRecord.requestBody)}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-xl border border-dashed border-border">
                  Raw wire inbound payload is not available or restricted by policy.
                </div>
              )}
            </TabsContent>

            {/* ── TAB 4: Source Document (Replica) ─────────────────────────── */}
            <TabsContent value="replica" className="m-0 space-y-4">
              {replicaRecord ? (
                <>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Document Key &amp; Version
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block font-mono">
                        {replicaRecord.recordKey} (v{replicaRecord.version})
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border bg-card">
                      <span className="text-muted-foreground block text-[11px] uppercase">
                        Stream &amp; Connection
                      </span>
                      <span className="font-semibold text-foreground mt-0.5 block truncate">
                        {replicaRecord.stream} ({replicaRecord.connectionId})
                      </span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground">
                      Source Document Replica Snapshot
                    </div>
                    <div className="rounded-xl border border-border overflow-hidden">
                      <MonacoCodeViewer
                        height={240}
                        value={stringifyJsonPretty(replicaRecord.data)}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-xl border border-dashed border-border">
                  No staging replica record found for this trace.
                </div>
              )}
            </TabsContent>

            {/* ── TAB 5: Cross-System Identity Mappings ─────────────────────── */}
            <TabsContent value="mappings" className="m-0 space-y-4">
              {gemMappings.length > 0 ? (
                <div className="space-y-3">
                  {gemMappings.map((gem) => (
                    <Card key={gem.id} className="border border-border bg-card">
                      <CardHeader className="p-3.5 pb-2">
                        <CardTitle className="text-xs font-semibold flex items-center justify-between">
                          <span className="text-primary font-mono">{gem.entityDomain}</span>
                          <CopyableIdPill value={gem.canonicalId} prefixLabel="Mapping ID" />
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-3.5 pt-1">
                        <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-muted/40 border border-border/60">
                          <div>
                            <span className="text-[10px] uppercase font-bold text-muted-foreground block">
                              Source Entity
                            </span>
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {gem.sourceEntityId}
                            </span>
                            <div className="text-[11px] text-muted-foreground">
                              {gem.sourceConnectionId}
                            </div>
                          </div>

                          <ArrowRightLeft className="h-4 w-4 text-primary shrink-0" />

                          <div className="text-right">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground block">
                              Target Entity
                            </span>
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {gem.destEntityId || 'Pending Resolution'}
                            </span>
                            <div className="text-[11px] text-muted-foreground">
                              {gem.destConnectionId || 'Target System'}
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-xl border border-dashed border-border">
                  No cross-system identity mapping entries recorded for this entity.
                </div>
              )}
            </TabsContent>

            {/* ── TAB 6: Lifecycle History ─────────────────────────────────── */}
            <TabsContent value="lifecycle" className="m-0 space-y-4">
              {traceEvents.length > 0 ? (
                <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-border">
                  {traceEvents.map((event) => {
                    const isError =
                      event.eventType.includes('FAILED') || event.eventType.includes('ERROR');
                    const isSuccess =
                      event.eventType.includes('DELIVERED') ||
                      event.eventType.includes('SUCCEEDED') ||
                      event.eventType.includes('MAPPED');

                    return (
                      <div key={event.id} className="relative">
                        <div
                          className={`absolute -left-6 top-1 h-3.5 w-3.5 rounded-full border-2 border-background ${
                            isError
                              ? 'bg-status-critical-fg'
                              : isSuccess
                                ? 'bg-status-healthy-fg'
                                : 'bg-primary'
                          }`}
                        />
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-semibold text-foreground">
                              {event.eventType.replace(/[._]/g, ' ')}
                            </span>
                            <span className="text-[11px] font-mono text-muted-foreground">
                              {formatRelativeTimestamp(event.createdAt)}
                            </span>
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Actor: <span className="font-mono">{event.actor}</span>
                          </div>
                          {event.metadata && Object.keys(event.metadata).length > 0 && (
                            <pre className="text-[11px] font-mono bg-muted/40 p-2 rounded border border-border/50 text-foreground overflow-x-auto">
                              {JSON.stringify(event.metadata, null, 2)}
                            </pre>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-xl border border-dashed border-border">
                  No chronological audit events found for this trace.
                </div>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
