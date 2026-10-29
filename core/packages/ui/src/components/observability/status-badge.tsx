import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  FlaskConical,
  RotateCcw,
  XCircle,
} from 'lucide-react';
import React from 'react';
import { cn } from '../../lib/utils';
import { Badge } from '../ui/badge';

export const StatusTone = {
  HEALTHY: 'healthy',
  WARNING: 'warning',
  CRITICAL: 'critical',
  SHADOW: 'shadow',
  REPLAY: 'replay',
  NEUTRAL: 'neutral',
} as const;

export type StatusToneValue = (typeof StatusTone)[keyof typeof StatusTone];

const TONE_CLASS_MAP: Readonly<Record<StatusToneValue, string>> = {
  healthy: 'bg-status-healthy-bg text-status-healthy-fg border-status-healthy-border',
  warning: 'bg-status-warning-bg text-status-warning-fg border-status-warning-border',
  critical: 'bg-status-critical-bg text-status-critical-fg border-status-critical-border',
  shadow: 'bg-status-shadow-bg text-status-shadow-fg border-status-shadow-border',
  replay: 'bg-status-replay-bg text-status-replay-fg border-status-replay-border',
  neutral: 'bg-muted text-muted-foreground border-border',
};

const TONE_ICON_MAP: Readonly<
  Record<StatusToneValue, React.ComponentType<{ className?: string }>>
> = {
  healthy: CheckCircle2,
  warning: AlertTriangle,
  critical: XCircle,
  shadow: FlaskConical,
  replay: RotateCcw,
  neutral: CircleDot,
};

export interface StatusBadgeProps {
  readonly label: string;
  readonly tone?: StatusToneValue;
  readonly icon?: React.ReactNode;
  readonly className?: string;
  readonly title?: string;
}

/**
 * Accessible status indicator that pairs iconography + solid border + text
 * so operational state is never communicated through color alone.
 */
export function StatusBadge({
  label,
  tone = StatusTone.NEUTRAL,
  icon,
  className,
  title,
}: StatusBadgeProps) {
  const DefaultIcon = TONE_ICON_MAP[tone];

  return (
    <Badge
      variant="outline"
      title={title ?? label}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-tight tabular-nums',
        TONE_CLASS_MAP[tone],
        className,
      )}
    >
      <span aria-hidden="true" className="inline-flex shrink-0">
        {icon ?? <DefaultIcon className="h-3.5 w-3.5" />}
      </span>
      <span>{label}</span>
    </Badge>
  );
}
