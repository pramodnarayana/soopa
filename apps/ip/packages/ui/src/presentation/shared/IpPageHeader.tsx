import { Button } from '@soopa/ui';
import { Search, Sparkles } from 'lucide-react';
import React from 'react';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';

export interface IpPageHeaderProps {
  readonly eyebrow?: string;
  readonly title: string;
  readonly subtitle: string;
  readonly actions?: React.ReactNode;
}

export function IpPageHeader({
  eyebrow = 'Integration Platform',
  title,
  subtitle,
  actions,
}: IpPageHeaderProps) {
  const { openCommandPalette } = useIpWorkspace();

  return (
    <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-center lg:justify-between">
      <div className="space-y-1">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-accent px-2.5 py-0.5 text-xs font-semibold text-brand-ink">
          <Sparkles className="h-3.5 w-3.5" />
          <span>{eyebrow}</span>
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{subtitle}</p>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={openCommandPalette}
          className="gap-2 rounded-lg text-xs text-muted-foreground hover:text-foreground"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Correlation Lookup</span>
          <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
            ⌘K
          </kbd>
        </Button>
        {actions}
      </div>
    </header>
  );
}
