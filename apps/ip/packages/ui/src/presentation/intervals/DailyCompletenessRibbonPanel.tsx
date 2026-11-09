import {
  ActivityHeatmap,
  type ActivityHeatmapCell,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  cn,
} from '@soopa/ui';
import { CheckCircle2, FilterX, Radio } from 'lucide-react';
import React, { useMemo } from 'react';
import type { IntervalWindowCompleteness } from '../../domain/intervals';

export interface DailyCompletenessRibbonPanelProps {
  readonly items: readonly IntervalWindowCompleteness[];
  readonly selectedFeederId: string | null;
  readonly onSelectFeeder: (feederId: string | null) => void;
  readonly serviceDate: string;
}

function resolveCompletenessVariant(pct: number): 'success' | 'warning' | 'destructive' {
  if (pct >= 100) {
    return 'success';
  }
  if (pct >= 95) {
    return 'warning';
  }
  return 'destructive';
}

function resolveProgressBarClass(pct: number): string {
  if (pct >= 100) {
    return 'bg-success';
  }
  if (pct >= 95) {
    return 'bg-warning';
  }
  return 'bg-destructive';
}

export function DailyCompletenessRibbonPanel({
  items,
  selectedFeederId,
  onSelectFeeder,
  serviceDate,
}: DailyCompletenessRibbonPanelProps) {
  const heatmapCells = useMemo<readonly ActivityHeatmapCell[]>(
    () =>
      items.map((item) => ({
        key: item.feederId,
        label: `${item.feederId} (${item.completenessPercentage.toFixed(1)}%)`,
        count: item.receivedIntervalsTotal,
        tone:
          item.completenessPercentage >= 100
            ? 'healthy'
            : item.completenessPercentage >= 95
              ? 'warning'
              : 'critical',
      })),
    [items],
  );

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle>96-Slot Daily Completeness Ribbon ({serviceDate})</CardTitle>
          <CardDescription>
            Click any feeder tile to filter the Time-of-Use (TOU) settlement rollups table below.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {selectedFeederId ? (
            <Button type="button" variant="outline" size="sm" onClick={() => onSelectFeeder(null)}>
              <FilterX className="h-3.5 w-3.5" />
              <span>Clear Feeder Filter ({selectedFeederId})</span>
            </Button>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {items.length === 0 ? (
          <div className="rounded-lg border border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
            No interval completeness windows recorded for {serviceDate}.
          </div>
        ) : (
          <>
            <ActivityHeatmap
              cells={heatmapCells}
              selectedKey={selectedFeederId}
              onSelectCell={(cell) =>
                onSelectFeeder(selectedFeederId === cell.key ? null : cell.key)
              }
              legendType="threshold"
            />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {items.map((item) => {
                const isSelected = selectedFeederId === item.feederId;
                const clampedPct = Math.min(100, Math.max(0, item.completenessPercentage));
                return (
                  <button
                    key={`${item.connectionId}:${item.streamName}:${item.feederId}`}
                    type="button"
                    onClick={() => onSelectFeeder(isSelected ? null : item.feederId)}
                    className={cn(
                      'group flex flex-col gap-2.5 rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-foreground/30',
                      isSelected && 'border-foreground ring-1 ring-foreground',
                    )}
                  >
                    <div className="flex w-full items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Radio className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
                        <span className="font-mono text-sm font-semibold text-foreground">
                          {item.feederId}
                        </span>
                      </div>
                      <Badge variant={resolveCompletenessVariant(item.completenessPercentage)}>
                        {item.completenessPercentage.toFixed(2)}%
                      </Badge>
                    </div>

                    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          'h-full transition-all',
                          resolveProgressBarClass(item.completenessPercentage),
                        )}
                        style={{ width: `${clampedPct}%` }}
                      />
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground tabular-nums">
                      <span>
                        {item.activeDeviceCount.toLocaleString()} devices ·{' '}
                        {item.expectedIntervalsPerDevice} slots/day
                      </span>
                      <span>
                        {item.receivedIntervalsTotal.toLocaleString()} /{' '}
                        {item.expectedIntervalsTotal.toLocaleString()} slots
                      </span>
                    </div>

                    <div className="flex items-center justify-between border-t border-border pt-2 text-xs tabular-nums">
                      <span className="inline-flex items-center gap-1 text-muted-foreground">
                        <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                        Valid: {item.validIntervalsTotal.toLocaleString()}
                      </span>
                      <span
                        className={cn(
                          'font-medium',
                          item.quarantinedIntervalsTotal > 0
                            ? 'text-destructive'
                            : 'text-muted-foreground',
                        )}
                      >
                        Quarantined: {item.quarantinedIntervalsTotal.toLocaleString()}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
