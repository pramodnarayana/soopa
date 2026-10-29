import React from 'react';
import { StatusBadge, StatusTone } from './status-badge';

export interface ReplayBadgeProps {
  readonly count?: number;
  readonly className?: string;
}

export function ReplayBadge({ count, className }: ReplayBadgeProps) {
  if ((count ?? 0) <= 0) {
    return null;
  }

  return (
    <StatusBadge
      tone={StatusTone.REPLAY}
      label={`Replayed (${count})`}
      title={`Replayed ${count} times`}
      className={className}
    />
  );
}
