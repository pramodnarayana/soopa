import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  MonacoCodeViewer,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { CloudDownload } from 'lucide-react';
import React from 'react';
import { PipelineLayer, type PipelineLayerValue } from '../../domain/enums';
import type {
  InboundRecord,
  IpTrace,
  NormalizationRejection,
  NormalizedRecord,
  OutboundRecord,
  ReplicaRecord,
  ReplicaRejection,
  TraceEventEntry,
} from '../../domain/trace';
import { GemRosettaStrip } from '../shared/GemRosettaStrip';
import {
  formatBytesCompact,
  formatRelativeTimestamp,
  stringifyJsonPretty,
} from '../shared/status-mapping';

function InboundWireStagePanel({
  record,
  hasUnhydratedS3,
  onHydrateS3,
}: {
  readonly record: InboundRecord | null;
  readonly hasUnhydratedS3: boolean;
  readonly onHydrateS3: () => void;
}) {
  if (!record) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No direct L1 InboundRecord on this child trace (replayed from downstream L2/L3/L5 state).
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span>L1 Raw Wire Capture · {record.appId}</span>
            <StatusBadge label={record.ingestionMode} tone={StatusTone.NEUTRAL} />
          </CardTitle>
          <CardDescription>
            Stream <span className="font-mono">{record.streamName}</span> ·{' '}
            {formatBytesCompact(record.requestSizeBytes)} ·{' '}
            {record.durationMs !== null ? `${record.durationMs}ms` : 'sync'} ·{' '}
            {formatRelativeTimestamp(record.receivedAt)}
          </CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CopyableIdPill value={record.requestSha256} prefixLabel="SHA-256" truncateLength={16} />
          {hasUnhydratedS3 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onHydrateS3}
              className="gap-1.5"
            >
              <CloudDownload className="h-3.5 w-3.5" />
              <span>Hydrate S3 Body</span>
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-muted-foreground uppercase">
            Request Payload & Redacted Headers
          </div>
          <MonacoCodeViewer
            height={280}
            value={stringifyJsonPretty({
              headers: record.requestHeaders,
              body: record.requestBody,
              s3OffloadKey: record.requestS3Key,
            })}
          />
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-muted-foreground uppercase">
            Wire Response ({record.responseStatusCode ?? 200})
          </div>
          <MonacoCodeViewer
            height={280}
            value={stringifyJsonPretty({
              statusCode: record.responseStatusCode,
              headers: record.responseHeaders,
              body: record.responseBody,
              s3OffloadKey: record.responseS3Key,
            })}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function ReplicaStagePanel({
  records,
  rejections,
}: {
  readonly records: readonly ReplicaRecord[];
  readonly rejections: readonly ReplicaRejection[];
}) {
  return (
    <div className="space-y-4">
      {rejections.map((rej) => (
        <Card key={rej.id} className="border-status-critical-border bg-status-critical-bg/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-status-critical-fg">
              <StatusBadge label={rej.reason} tone={StatusTone.CRITICAL} />
              <span className="font-mono text-sm">
                Stream {rej.stream} · Record #{rej.recordIndex}
              </span>
            </CardTitle>
            <CardDescription className="text-status-critical-fg">{rej.detail}</CardDescription>
          </CardHeader>
        </Card>
      ))}

      {records.length === 0 && rejections.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No L2 Universal Replica records materialized on this trace.
          </CardContent>
        </Card>
      ) : null}

      {records.map((replica) => (
        <Card key={replica.id}>
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="font-mono text-sm">
                {replica.stream} · Key: {replica.recordKey}
              </CardTitle>
              <CardDescription>
                Generation #{replica.generationId} · Version v{replica.version} · Cursor:{' '}
                <span className="font-mono">{replica.cursorValue ?? 'none'}</span>
              </CardDescription>
            </div>
            <CopyableIdPill value={replica.dataHash} prefixLabel="Hash" truncateLength={16} />
          </CardHeader>
          <CardContent>
            <MonacoCodeViewer height={240} value={stringifyJsonPretty(replica.data)} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CanonicalStagePanel({
  records,
  rejections,
  trace,
}: {
  readonly records: readonly NormalizedRecord[];
  readonly rejections: readonly NormalizationRejection[];
  readonly trace: IpTrace;
}) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>GlobalEntityMap (GEM) Rosetta Cross-References</CardTitle>
          <CardDescription>
            Bidirectional identity bindings linking source system keys, canonical UUIDs, and
            destination ERP/CRM IDs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GemRosettaStrip mappings={trace.entityMappings} />
        </CardContent>
      </Card>

      {rejections.map((rej) => (
        <Card key={rej.id} className="border-status-critical-border bg-status-critical-bg/40">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-status-critical-fg">
              <StatusBadge label={rej.reasonCode} tone={StatusTone.CRITICAL} />
              <span className="font-mono text-sm">
                {rej.transformationId} (v{rej.transformationVersion})
              </span>
              {rej.fieldPath ? <CopyableIdPill value={rej.fieldPath} prefixLabel="Field" /> : null}
            </CardTitle>
            <CardDescription className="text-status-critical-fg">{rej.detail}</CardDescription>
          </CardHeader>
        </Card>
      ))}

      {records.map((norm) => (
        <Card key={norm.id}>
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="font-mono text-sm">{norm.canonicalType}</CardTitle>
              <CardDescription>
                Source ID <span className="font-mono">{norm.sourceId}</span> · Normalized{' '}
                {formatRelativeTimestamp(norm.normalizedAt)}
              </CardDescription>
            </div>
            <CopyableIdPill value={norm.id} prefixLabel="Entity ID" truncateLength={16} />
          </CardHeader>
          <CardContent>
            <MonacoCodeViewer height={260} value={stringifyJsonPretty(norm.canonicalData)} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function StitchEventsStagePanel({
  events,
  onOpenStitches,
}: {
  readonly events: readonly TraceEventEntry[];
  readonly onOpenStitches: () => void;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>L4 Orchestration & Chronological Audit Events ({events.length})</CardTitle>
          <CardDescription>
            Immutable trace transition log across ingestion, canonical fan-out, Stitch step
            execution, and replay actors.
          </CardDescription>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onOpenStitches}>
          Inspect Durable Stitch Runs
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {events.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No orchestration timeline events recorded on this trace yet.
          </p>
        ) : (
          events.map((evt) => (
            <div key={evt.id} className="rounded-xl border border-border bg-muted/20 p-3.5 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="rounded-md bg-accent px-2 py-0.5 font-mono font-semibold text-brand-ink">
                    {evt.eventType}
                  </span>
                  <span className="text-muted-foreground">Actor: {evt.actor}</span>
                </div>
                <span className="font-mono text-muted-foreground tabular-nums">
                  {formatRelativeTimestamp(evt.createdAt)}
                </span>
              </div>
              {evt.metadata ? (
                <pre className="mt-2 overflow-x-auto rounded-lg bg-card p-2.5 font-mono text-xs text-foreground">
                  {stringifyJsonPretty(evt.metadata)}
                </pre>
              ) : null}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function OutboundDeliveryCard({ record }: { readonly record: OutboundRecord }) {
  const isFailure = record.status === 'FAILED' || record.failureCategory !== null;
  const tone = isFailure ? StatusTone.CRITICAL : StatusTone.HEALTHY;

  return (
    <Card className={isFailure ? 'border-status-critical-border' : undefined}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="flex flex-wrap items-center gap-2 font-mono text-sm">
            <StatusBadge
              label={`${record.httpMethod} ${record.responseStatusCode ?? 'ERR'}`}
              tone={tone}
            />
            <span>{record.targetUrl}</span>
          </CardTitle>
          <CardDescription>
            Connector <span className="font-mono">{record.appId}</span> · Operation{' '}
            <span className="font-mono">{record.operation}</span> · Attempt #{record.attemptNumber}{' '}
            · {record.durationMs !== null ? `${record.durationMs}ms` : '—'}
          </CardDescription>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {record.failureCategory ? (
            <StatusBadge label={record.failureCategory} tone={StatusTone.CRITICAL} />
          ) : null}
          {record.retryAfterSeconds !== null ? (
            <StatusBadge
              label={`Retry-After: ${record.retryAfterSeconds}s`}
              tone={StatusTone.WARNING}
            />
          ) : null}
          {record.externalRecordId ? (
            <CopyableIdPill value={record.externalRecordId} prefixLabel="External ID" />
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {record.errorMessage ? (
          <div className="rounded-lg border border-status-critical-border bg-status-critical-bg px-3 py-2 text-xs text-status-critical-fg">
            {record.errorMessage}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground uppercase">
              Outbound Request (Redacted)
            </div>
            <MonacoCodeViewer
              height={240}
              value={stringifyJsonPretty({
                idempotencyKey: record.idempotencyKey,
                headers: record.requestHeaders,
                body: record.requestBody,
              })}
            />
          </div>
          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground uppercase">
              Destination Wire Response
            </div>
            <MonacoCodeViewer
              height={240}
              value={stringifyJsonPretty({
                statusCode: record.responseStatusCode,
                headers: record.responseHeaders,
                body: record.responseBody,
              })}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export interface TraceWaterfallStageContentProps {
  readonly activeLayer: PipelineLayerValue;
  readonly trace: IpTrace;
  readonly hasUnhydratedS3: boolean;
  readonly onHydrateS3: () => void;
  readonly onOpenStitches: () => void;
}

export function TraceWaterfallStageContent({
  activeLayer,
  trace,
  hasUnhydratedS3,
  onHydrateS3,
  onOpenStitches,
}: TraceWaterfallStageContentProps) {
  if (activeLayer === PipelineLayer.L1_INGEST) {
    return (
      <InboundWireStagePanel
        record={trace.inboundRecord}
        hasUnhydratedS3={hasUnhydratedS3}
        onHydrateS3={onHydrateS3}
      />
    );
  }
  if (activeLayer === PipelineLayer.L2_REPLICA) {
    return (
      <ReplicaStagePanel records={trace.replicaRecords} rejections={trace.replicaRejections} />
    );
  }
  if (activeLayer === PipelineLayer.L3_NORMALIZE) {
    return (
      <CanonicalStagePanel
        records={trace.normalizedRecords}
        rejections={trace.normalizationRejections}
        trace={trace}
      />
    );
  }
  if (activeLayer === PipelineLayer.L4_STITCH) {
    return <StitchEventsStagePanel events={trace.traceEvents} onOpenStitches={onOpenStitches} />;
  }
  if (trace.outboundRecords.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No L5 OutboundRecord HTTP deliveries have executed for this trace yet.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      {trace.outboundRecords.map((rec) => (
        <OutboundDeliveryCard key={rec.id} record={rec} />
      ))}
    </div>
  );
}
