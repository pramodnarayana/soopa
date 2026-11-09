import * as React from 'react';
import { cn } from '../../lib/utils';
import { Card, CardContent } from './card';

export interface StatCardProps {
  readonly title: React.ReactNode;
  readonly value: React.ReactNode;
  readonly subtitle?: React.ReactNode;
  readonly icon?: React.ReactNode;
  readonly onClick?: () => void;
  readonly className?: string;
}

export function StatCard({ title, value, subtitle, icon, onClick, className }: StatCardProps) {
  return (
    <Card
      onClick={onClick}
      className={cn(
        'group relative overflow-hidden transition-colors hover:border-foreground/20',
        onClick && 'cursor-pointer',
        className,
      )}
    >
      <CardContent className="flex items-center gap-3 p-4">
        {icon ? (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:text-foreground [&_svg]:size-[18px]">
            {icon}
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs text-muted-foreground">{title}</div>
          <div className="mt-0.5 text-2xl font-semibold leading-tight tracking-tight text-foreground tabular-nums">
            {value}
          </div>
          {subtitle ? (
            <div className="mt-0.5 truncate text-xs text-muted-foreground">{subtitle}</div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
