import React, { lazy, Suspense } from 'react';
import { cn } from '../../lib/utils';
import { Skeleton } from '../ui/skeleton';
import { useEffectiveMonacoTheme } from './monaco-config';

const LazyDiffEditor = lazy(() =>
  import('./monaco-runtime').then((mod) => ({ default: mod.SelfHostedMonacoDiffEditor })),
);

export interface MonacoJsonDiffViewerProps {
  readonly originalValue: string;
  readonly modifiedValue: string;
  readonly language?: string;
  readonly height?: string | number;
  readonly onModifiedChange?: (nextModified: string) => void;
  readonly className?: string;
}

export function MonacoJsonDiffViewer({
  originalValue,
  modifiedValue,
  language = 'json',
  height = 380,
  onModifiedChange,
  className,
}: MonacoJsonDiffViewerProps): React.JSX.Element {
  const effectiveTheme = useEffectiveMonacoTheme();
  const isModifiedEditable = onModifiedChange !== undefined;

  return (
    <div
      style={{ height }}
      className={cn('overflow-hidden rounded-xl border border-border bg-card', className)}
    >
      <Suspense fallback={<Skeleton className="h-full w-full rounded-none" />}>
        <LazyDiffEditor
          height="100%"
          language={language}
          original={originalValue}
          modified={modifiedValue}
          theme={effectiveTheme}
          onMount={(editor) => {
            if (!onModifiedChange) {
              return;
            }
            const modifiedEditor = editor.getModifiedEditor();
            modifiedEditor.onDidChangeModelContent(() => {
              onModifiedChange(modifiedEditor.getValue());
            });
          }}
          options={{
            automaticLayout: true,
            readOnly: !isModifiedEditable,
            originalEditable: false,
            renderSideBySide: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            padding: { top: 12, bottom: 12 },
            fontSize: 12,
          }}
        />
      </Suspense>
    </div>
  );
}
