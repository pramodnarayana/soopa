import * as React from 'react';
import { cn } from '../../lib/utils';

export interface DescriptionItem {
  readonly key?: string;
  readonly label: React.ReactNode;
  readonly children: React.ReactNode;
  readonly span?: 1 | 2;
}

export interface DescriptionListProps {
  readonly title?: React.ReactNode;
  readonly items: readonly DescriptionItem[];
  readonly columns?: 1 | 2;
  readonly className?: string;
}

export function DescriptionList({ title, items, columns = 1, className }: DescriptionListProps) {
  return (
    <div className={cn('overflow-hidden rounded-md border border-border bg-border', className)}>
      {title ? (
        <div className="border-b border-border bg-muted/50 px-3 py-2 text-sm font-semibold text-foreground">
          {title}
        </div>
      ) : null}
      <div
        className={cn(
          'grid gap-px bg-border',
          columns === 2 ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1',
        )}
      >
        {items.map((item, idx) => (
          <div
            key={item.key ?? (typeof item.label === 'string' ? item.label : idx)}
            className={cn(
              'grid grid-cols-3 bg-background',
              columns === 2 && item.span === 2 && 'md:col-span-2',
            )}
          >
            <div className="col-span-1 border-r border-border bg-muted/60 px-3 py-2 text-sm font-medium text-muted-foreground">
              {item.label}
            </div>
            <div className="col-span-2 break-words px-3 py-2 text-sm text-foreground">
              {item.children}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
