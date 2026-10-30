import { X } from 'lucide-react';
import React from 'react';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';

export interface SplitInspectorDrawerProps {
  readonly title: string;
  readonly subtitle?: React.ReactNode;
  readonly headerActions?: React.ReactNode;
  readonly onClose?: () => void;
  readonly children: React.ReactNode;
  readonly className?: string;
}

export function SplitInspectorDrawer({
  title,
  subtitle,
  headerActions,
  onClose,
  children,
  className,
}: SplitInspectorDrawerProps) {
  return (
    <aside
      aria-label={title}
      className={cn(
        'flex flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-xs',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border bg-muted/40 px-5 py-4">
        <div className="min-w-0 space-y-1">
          <h3 className="truncate text-base font-semibold text-foreground">{title}</h3>
          {subtitle ? <div className="text-xs text-muted-foreground">{subtitle}</div> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {headerActions}
          {onClose ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onClose}
              aria-label="Close inspector"
              className="h-8 w-8"
            >
              <X className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5">{children}</div>
    </aside>
  );
}
