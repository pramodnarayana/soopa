import { Check, Copy } from 'lucide-react';
import React from 'react';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { useClipboardCopy } from './use-clipboard-copy';

export interface CopyableIdPillProps {
  readonly value: string;
  readonly prefixLabel?: string;
  readonly truncateLength?: number;
  readonly className?: string;
}

function formatDisplayValue(value: string, truncateLength?: number): string {
  if (!truncateLength || value.length <= truncateLength) {
    return value;
  }
  const head = Math.max(6, Math.floor(truncateLength * 0.65));
  const tail = Math.max(4, truncateLength - head);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function CopyableIdPill({
  value,
  prefixLabel,
  truncateLength,
  className,
}: CopyableIdPillProps) {
  const { copied, copyText } = useClipboardCopy(1_600);

  const handleCopy = (event: React.MouseEvent<HTMLButtonElement>): void => {
    event.stopPropagation();
    void copyText(value);
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-2 py-0.5 font-mono text-xs text-foreground tabular-nums',
        className,
      )}
      title={value}
    >
      {prefixLabel ? (
        <span className="font-sans font-medium text-muted-foreground">{prefixLabel}:</span>
      ) : null}
      <span>{formatDisplayValue(value, truncateLength)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={handleCopy}
        aria-label={copied ? `Copied ${value}` : `Copy ${value}`}
        className="h-4 w-4 rounded-sm p-0 text-muted-foreground hover:text-foreground"
      >
        {copied ? (
          <Check className="h-3 w-3 text-status-healthy-fg" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </Button>
    </span>
  );
}
