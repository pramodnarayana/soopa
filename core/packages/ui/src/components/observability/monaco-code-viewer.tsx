import type { BeforeMount } from '@monaco-editor/react';
import { Check, Copy } from 'lucide-react';
import { useTheme } from 'next-themes';
import React, { lazy, Suspense } from 'react';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { Skeleton } from '../ui/skeleton';
import { useClipboardCopy } from './use-clipboard-copy';

const LazyEditor = lazy(() => import('@monaco-editor/react'));

export interface MonacoCodeViewerProps {
  readonly value: string;
  readonly language?: string;
  readonly className?: string;
  readonly height?: string | number;
  readonly readOnly?: boolean;
  readonly onChange?: (nextValue: string) => void;
  readonly customThemeName?: string;
  readonly beforeMount?: BeforeMount;
}

export function MonacoCodeViewer({
  value,
  language = 'json',
  className,
  height = 320,
  readOnly = true,
  onChange,
  customThemeName,
  beforeMount,
}: MonacoCodeViewerProps) {
  const { copied, copyText } = useClipboardCopy(1_800);
  const { resolvedTheme } = useTheme();
  const effectiveTheme = customThemeName ?? (resolvedTheme === 'dark' ? 'vs-dark' : 'vs');

  const handleCopy = (): void => {
    void copyText(value);
  };

  return (
    <div
      style={{ height }}
      className={cn(
        'group relative overflow-hidden rounded-xl border border-border bg-card',
        className,
      )}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleCopy}
        className="absolute right-4 bottom-3 z-20 gap-1.5 bg-card/95 text-xs opacity-0 shadow-xs transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
      >
        {copied ? (
          <>
            <Check className="h-3.5 w-3.5 text-status-healthy-fg" />
            <span className="text-status-healthy-fg">Copied</span>
          </>
        ) : (
          <>
            <Copy className="h-3.5 w-3.5" />
            <span>Copy</span>
          </>
        )}
      </Button>

      <Suspense fallback={<Skeleton className="h-full w-full rounded-none" />}>
        <LazyEditor
          height="100%"
          language={language}
          value={value}
          theme={effectiveTheme}
          beforeMount={beforeMount}
          onChange={onChange ? (val) => onChange(val ?? '') : undefined}
          options={{
            readOnly,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            lineNumbersMinChars: 3,
            wordWrap: 'on',
            folding: true,
            padding: { top: 12, bottom: 12 },
            renderLineHighlight: readOnly ? 'none' : 'line',
            hideCursorInOverviewRuler: true,
            overviewRulerBorder: false,
            scrollbar: {
              verticalScrollbarSize: 8,
              horizontalScrollbarSize: 8,
            },
            fontSize: 12,
          }}
        />
      </Suspense>
    </div>
  );
}

export { MonacoCodeViewer as CodeViewer };
