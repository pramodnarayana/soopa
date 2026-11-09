import * as React from 'react';
import { cn } from '../../lib/utils';

export interface ActivityHeatmapCell {
  readonly key: string;
  readonly label: string;
  readonly count: number;
  readonly tone?: 'default' | 'healthy' | 'warning' | 'critical';
}

export interface ActivityHeatmapProps {
  readonly cells: readonly ActivityHeatmapCell[];
  readonly selectedKey?: string | null;
  readonly onSelectCell?: (cell: ActivityHeatmapCell) => void;
  readonly lessLabel?: string;
  readonly moreLabel?: string;
  readonly className?: string;
  readonly legendType?: 'volume' | 'threshold';
  readonly thresholdLabels?: {
    readonly critical?: string;
    readonly warning?: string;
    readonly healthy?: string;
  };
}

const LEVEL_CLASSES = [
  'bg-muted',
  'bg-chart-1/25',
  'bg-chart-1/50',
  'bg-chart-1/75',
  'bg-chart-1',
] as const;

const TONE_CLASS_OVERRIDES: Readonly<Record<NonNullable<ActivityHeatmapCell['tone']>, string>> = {
  default: '',
  healthy: 'bg-success',
  warning: 'bg-warning',
  critical: 'bg-destructive',
};

export function ActivityHeatmap({
  cells,
  selectedKey,
  onSelectCell,
  lessLabel = 'Less',
  moreLabel = 'More',
  className,
  legendType = 'volume',
  thresholdLabels,
}: ActivityHeatmapProps) {
  const max = React.useMemo(
    () => cells.reduce((acc, cell) => (cell.count > acc ? cell.count : acc), 0),
    [cells],
  );

  const resolveLevel = (count: number): 0 | 1 | 2 | 3 | 4 => {
    if (count <= 0 || max <= 0) {
      return 0;
    }
    const ratio = count / max;
    if (ratio < 0.25) return 1;
    if (ratio < 0.5) return 2;
    if (ratio < 0.75) return 3;
    return 4;
  };

  return (
    <div className={cn('w-full space-y-2', className)}>
      <div className="flex flex-wrap gap-1">
        {cells.map((cell) => {
          const level = resolveLevel(cell.count);
          const toneOverride = cell.tone ? TONE_CLASS_OVERRIDES[cell.tone] : '';
          const isSelected = selectedKey === cell.key;
          return (
            <button
              key={cell.key}
              type="button"
              title={`${cell.label}: ${cell.count}`}
              aria-label={`${cell.label}: ${cell.count}`}
              onClick={() => onSelectCell?.(cell)}
              className={cn(
                'h-3.5 w-3.5 rounded-[2px] transition-transform hover:scale-125 focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none',
                toneOverride || LEVEL_CLASSES[level],
                isSelected && 'ring-2 ring-foreground ring-offset-1 ring-offset-background',
              )}
            />
          );
        })}
      </div>
      {legendType === 'threshold' ? (
        <div className="flex items-center justify-end gap-3 text-[10px] text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-destructive" />
            <span>{thresholdLabels?.critical ?? '<95% (Critical)'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-warning" />
            <span>{thresholdLabels?.warning ?? '95% – <100% (Warning)'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-success" />
            <span>{thresholdLabels?.healthy ?? '100% (Complete)'}</span>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-1.5 text-[10px] text-muted-foreground">
          <span>{lessLabel}</span>
          {LEVEL_CLASSES.map((cls) => (
            <span key={cls} className={cn('h-2.5 w-2.5 rounded-[2px]', cls)} />
          ))}
          <span>{moreLabel}</span>
        </div>
      )}
    </div>
  );
}
