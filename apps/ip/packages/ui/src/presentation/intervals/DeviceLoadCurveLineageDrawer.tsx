import {
  Badge,
  Button,
  CopyableIdPill,
  cn,
  DescriptionList,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@soopa/ui';
import { AlertTriangle, ExternalLink, Layers } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { CimQualityStatus, TariffBucket } from '../../domain/enums';
import type { IntervalLineagePoint, IntervalLineageTrace } from '../../domain/intervals';

export interface DeviceLoadCurveLineageDrawerProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly trace: IntervalLineageTrace | undefined;
  readonly isLoading?: boolean;
  readonly onOpenBatchTrace?: (traceId: string) => void;
}

function resolveBarColorClass(point: IntervalLineagePoint): string {
  if (point.qualityStatus === CimQualityStatus.QUARANTINED_SPIKE) {
    return 'bg-destructive';
  }
  if (
    point.qualityStatus === CimQualityStatus.POWER_DOWN ||
    point.qualityStatus === CimQualityStatus.ESTIMATED_VEE ||
    point.qualityStatus === CimQualityStatus.ESTIMATED_MANUAL ||
    point.qualityStatus === CimQualityStatus.DST_AMBIGUOUS
  ) {
    return 'bg-warning';
  }
  if (point.tariffBucket === TariffBucket.PEAK) {
    return 'bg-chart-1';
  }
  if (point.tariffBucket === TariffBucket.SHOULDER) {
    return 'bg-chart-2';
  }
  return 'bg-chart-3';
}

function resolveQualityBadgeVariant(status: string): 'success' | 'warning' | 'destructive' {
  if (status === CimQualityStatus.VALID) {
    return 'success';
  }
  if (status === CimQualityStatus.QUARANTINED_SPIKE) {
    return 'destructive';
  }
  return 'warning';
}

export function DeviceLoadCurveLineageDrawer({
  open,
  onOpenChange,
  trace,
  isLoading = false,
  onOpenBatchTrace,
}: DeviceLoadCurveLineageDrawerProps) {
  const intervals = trace?.intervals ?? [];
  const [selectedIndex, setSelectedIndex] = useState(0);

  const effectiveSelectedIndex =
    selectedIndex >= 0 && selectedIndex < intervals.length ? selectedIndex : 0;
  const selectedPoint = intervals[effectiveSelectedIndex] ?? null;

  const maxDelivered = useMemo(() => {
    let maxVal = 0.01;
    for (const pt of intervals) {
      const parsed = Number.parseFloat(pt.deliveredVolume);
      if (Number.isFinite(parsed) && parsed > maxVal) {
        maxVal = parsed;
      }
    }
    return maxVal;
  }, [intervals]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto p-6 sm:max-w-[720px]">
        <SheetHeader className="p-0 pb-4">
          <SheetTitle className="flex items-center gap-2 font-mono text-base">
            <span>Device 96-Slot Load Curve &amp; Batch Lineage</span>
            {trace ? <Badge variant="outline">{trace.sourceDeviceId}</Badge> : null}
          </SheetTitle>
          <SheetDescription>
            Two-Tier Traceability: click any 15-minute bar to inspect its L1/L2/L3 Parquet file URI,
            row offset, VEE quality status, and settlement receipt.
          </SheetDescription>
        </SheetHeader>

        {isLoading ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Loading 96-slot interval lineage...
          </div>
        ) : !trace || intervals.length === 0 ? (
          <div className="rounded-lg border border-border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
            No interval readings recorded for this device on the selected service date.
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs tabular-nums">
              <span>
                Service Date: <strong>{trace.serviceDate}</strong>
              </span>
              <span>
                Total Slots: <strong>{trace.totalIntervals}</strong>
              </span>
              <span>
                Valid: <strong>{trace.validIntervals}</strong>
              </span>
              <span
                className={
                  trace.quarantinedIntervals > 0 ? 'font-semibold text-destructive' : undefined
                }
              >
                Quarantined: <strong>{trace.quarantinedIntervals}</strong>
              </span>
            </div>

            {/* 96-Slot Interactive Bar Chart */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  15-Minute Interval Load Profile ({intervals.length} slots)
                </span>
                <div className="flex flex-wrap items-center gap-3 text-[11px]">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-xs bg-chart-1" /> Peak
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-xs bg-chart-2" /> Shoulder
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-xs bg-chart-3" /> Off-Peak
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-xs bg-destructive" /> Quarantined Spike
                  </span>
                </div>
              </div>

              <div
                role="listbox"
                aria-label="96-slot interval bars"
                className="flex h-32 items-end gap-0.5 border-b border-border pt-4 pb-1"
              >
                {intervals.map((pt, idx) => {
                  const val = Number.parseFloat(pt.deliveredVolume);
                  const heightPct = Number.isFinite(val)
                    ? Math.max(8, Math.min(100, Math.round((val / maxDelivered) * 100)))
                    : 8;
                  const isSelected = idx === effectiveSelectedIndex;
                  return (
                    <button
                      key={pt.intervalEndUtc}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      title={`${pt.intervalEndUtc} · ${pt.deliveredVolume} (${pt.qualityStatus})`}
                      onClick={() => setSelectedIndex(idx)}
                      className={cn(
                        'flex-1 rounded-t-[2px] transition-opacity hover:opacity-100 focus:outline-none',
                        resolveBarColorClass(pt),
                        isSelected ? 'opacity-100 ring-1 ring-foreground' : 'opacity-75',
                      )}
                      style={{ height: `${heightPct}%` }}
                    />
                  );
                })}
              </div>
            </div>

            {/* Selected Slot & Two-Tier Macro-Batch Lineage DescriptionList */}
            {selectedPoint ? (
              <div className="space-y-4">
                {selectedPoint.quarantineReason ? (
                  <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <div className="font-semibold">VEE Quarantine Reason</div>
                      <div className="mt-0.5">{selectedPoint.quarantineReason}</div>
                    </div>
                  </div>
                ) : null}

                <DescriptionList
                  title="Selected 15-Minute Interval Reading"
                  columns={2}
                  items={[
                    {
                      label: 'Interval End (UTC)',
                      children: (
                        <span className="font-mono text-xs tabular-nums">
                          {selectedPoint.intervalEndUtc}
                        </span>
                      ),
                    },
                    {
                      label: 'Quality Status',
                      children: (
                        <Badge variant={resolveQualityBadgeVariant(selectedPoint.qualityStatus)}>
                          {selectedPoint.qualityStatus}
                        </Badge>
                      ),
                    },
                    {
                      label: 'Tariff Bucket',
                      children: <Badge variant="outline">{selectedPoint.tariffBucket}</Badge>,
                    },
                    {
                      label: 'Delivered / Received',
                      children: (
                        <span className="font-mono text-xs tabular-nums">
                          {selectedPoint.deliveredVolume} / {selectedPoint.receivedVolume}
                        </span>
                      ),
                    },
                    {
                      label: 'Reactive / Voltage',
                      children: (
                        <span className="font-mono text-xs tabular-nums">
                          {selectedPoint.reactiveVolume} · {selectedPoint.voltageV.toFixed(1)} V
                        </span>
                      ),
                    },
                    {
                      label: 'Topology (Sub / Feeder)',
                      children: (
                        <span className="font-mono text-xs">
                          {selectedPoint.substationId} / {selectedPoint.feederId} (
                          {selectedPoint.endpointLocationId})
                        </span>
                      ),
                    },
                  ]}
                />

                <DescriptionList
                  title="Two-Tier Macro-Batch Lineage (L1 → L3 Provenance)"
                  columns={1}
                  items={[
                    {
                      label: 'Source Batch & Row',
                      children: (
                        <div className="flex flex-wrap items-center gap-2">
                          <CopyableIdPill value={selectedPoint.sourceBatchId} />
                          <Badge variant="secondary" className="font-mono">
                            Parquet Row #{selectedPoint.parquetRowOffset}
                          </Badge>
                          <Badge variant="outline">{selectedPoint.priorityLane}</Badge>
                        </div>
                      ),
                    },
                    {
                      label: 'L1 Raw Object URI',
                      children: (
                        <code className="break-all font-mono text-xs">
                          {selectedPoint.l1RawUri}
                        </code>
                      ),
                    },
                    {
                      label: 'L2 / L3 Parquet URIs',
                      children: (
                        <div className="space-y-1 font-mono text-xs">
                          <div className="break-all">L2: {selectedPoint.l2ReplicaUri ?? '—'}</div>
                          <div className="break-all">L3: {selectedPoint.l3CanonicalUri ?? '—'}</div>
                        </div>
                      ),
                    },
                    {
                      label: 'Payload SHA-256',
                      children: (
                        <CopyableIdPill value={selectedPoint.payloadSha256} truncateLength={24} />
                      ),
                    },
                    {
                      label: 'Settlement Receipt',
                      children: selectedPoint.deliveryReceiptId ? (
                        <CopyableIdPill value={selectedPoint.deliveryReceiptId} />
                      ) : (
                        <span className="text-xs text-muted-foreground">Pending settlement</span>
                      ),
                    },
                  ]}
                />

                {onOpenBatchTrace ? (
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => onOpenBatchTrace(selectedPoint.traceId)}
                    >
                      <Layers className="h-4 w-4" />
                      <span>Open Full L1–L5 Batch Trace ({selectedPoint.traceId})</span>
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
