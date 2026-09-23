import { Badge } from '@soopa/ui';
import React from 'react';

export function ReplayBadge({ count, className }: { count?: number; className?: string }) {
  if ((count ?? 0) <= 0) return null;

  return (
    <Badge
      variant="outline"
      className={`bg-purple-100 text-purple-700 border-purple-300 font-bold uppercase tracking-wider text-xs px-2 py-1 ${className || ''}`}
      title={`Replayed ${count} times`}
    >
      Replayed({count})
    </Badge>
  );
}
