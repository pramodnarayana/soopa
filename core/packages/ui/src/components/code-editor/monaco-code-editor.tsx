import type { OnMount } from '@monaco-editor/react';
import { FileCode2, UploadCloud, X } from 'lucide-react';
import React, { lazy, Suspense, useEffect, useId, useRef, useState } from 'react';
import { cn } from '../../lib/utils';
import { Skeleton } from '../ui/skeleton';
import {
  type MonacoBeforeMount,
  type MonacoOnMount,
  type MonacoOnValidate,
  useEffectiveMonacoTheme,
} from './monaco-config';

const LazyEditor = lazy(() =>
  import('./monaco-runtime').then((mod) => ({ default: mod.SelfHostedMonacoEditor })),
);

const DEFAULT_MAX_UPLOAD_BYTES = 1_048_576;

export const MonacoFileToolbarVisibility = {
  EMPTY_ONLY: 'EMPTY_ONLY',
  ALWAYS: 'ALWAYS',
} as const;

export type MonacoFileToolbarVisibilityValue =
  (typeof MonacoFileToolbarVisibility)[keyof typeof MonacoFileToolbarVisibility];

export interface MonacoFileTransformSuccess {
  readonly ok: true;
  readonly content: string;
}

export interface MonacoFileTransformRejection {
  readonly ok: false;
  readonly reason: string;
}

export type MonacoFileTransformOutcome = MonacoFileTransformSuccess | MonacoFileTransformRejection;

export interface MonacoFileUploadConfig {
  readonly accept?: string;
  readonly maxBytes?: number;
  readonly buttonLabel?: string;
  readonly emptyPrompt?: string | null;
  readonly statusText?: string | null;
  readonly toolbarVisibility?: MonacoFileToolbarVisibilityValue;
  readonly extraActions?: React.ReactNode;
  readonly transformLoadedFile?: (
    text: string,
    file: File,
  ) => MonacoFileTransformOutcome | Promise<MonacoFileTransformOutcome>;
  readonly onFileAccepted?: (file: File, content: string) => void;
}

export interface MonacoCodeEditorProps {
  readonly value: string;
  readonly onChange: (nextValue: string) => void;
  readonly language?: string;
  readonly className?: string;
  readonly height?: string | number;
  readonly fontSize?: number;
  readonly customThemeName?: string;
  readonly ariaLabelledBy?: string;
  readonly cornerPlaceholder?: string;
  readonly statusBanner?: React.ReactNode;
  readonly fileUpload?: MonacoFileUploadConfig;
  readonly beforeMount?: MonacoBeforeMount;
  readonly onMount?: MonacoOnMount;
  readonly onValidate?: MonacoOnValidate;
}

export interface DragContainmentTarget {
  containsNode(candidate: unknown): boolean;
}

export function isDragLeavingContainer(
  container: DragContainmentTarget,
  relatedTarget: unknown,
): boolean {
  if (relatedTarget === null || relatedTarget === undefined) {
    return true;
  }
  return !container.containsNode(relatedTarget);
}

function wrapDomContainment(element: Element): DragContainmentTarget {
  return {
    containsNode: (candidate: unknown): boolean =>
      typeof Node !== 'undefined' && candidate instanceof Node && element.contains(candidate),
  };
}

function formatByteLimit(bytes: number): string {
  if (bytes >= 1_048_576 && bytes % 1_048_576 === 0) {
    return `${bytes / 1_048_576}MB`;
  }
  if (bytes >= 1_024) {
    return `${Math.round(bytes / 1_024)}KB`;
  }
  return `${bytes}B`;
}

export async function processUploadedEditorFile(
  file: File,
  config: MonacoFileUploadConfig,
): Promise<MonacoFileTransformOutcome> {
  const maxBytes = config.maxBytes ?? DEFAULT_MAX_UPLOAD_BYTES;
  if (file.size > maxBytes) {
    return {
      ok: false,
      reason: `File size exceeds ${formatByteLimit(maxBytes)} limit. Please upload a smaller file.`,
    };
  }

  let rawText: string;
  try {
    rawText = await file.text();
  } catch (err) {
    const detail = err instanceof Error ? err.message : 'Unable to read file contents.';
    return { ok: false, reason: `Failed to read file: ${detail}` };
  }

  if (config.transformLoadedFile) {
    return await config.transformLoadedFile(rawText, file);
  }

  return { ok: true, content: rawText };
}

export function MonacoCodeEditor({
  value,
  onChange,
  language = 'json',
  className,
  height,
  fontSize = 13,
  customThemeName,
  ariaLabelledBy,
  cornerPlaceholder,
  statusBanner,
  fileUpload,
  beforeMount,
  onMount,
  onValidate,
}: MonacoCodeEditorProps): React.JSX.Element {
  const fileInputId = useId();
  const effectiveTheme = useEffectiveMonacoTheme(customThemeName);

  const [isDragging, setIsDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const applyFile = async (file: File): Promise<void> => {
    if (!fileUpload) {
      return;
    }
    setFileError(null);
    const outcome = await processUploadedEditorFile(file, fileUpload);
    if (!outcome.ok) {
      setFileError(outcome.reason);
      return;
    }
    onChange(outcome.content);
    fileUpload.onFileAccepted?.(file, outcome.content);
  };

  const hasFileUpload = fileUpload !== undefined;
  const applyFileRef = useRef(applyFile);
  const hasFileUploadRef = useRef(hasFileUpload);

  useEffect(() => {
    applyFileRef.current = applyFile;
    hasFileUploadRef.current = hasFileUpload;
  });

  const handleContainerDragOver = (event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    setIsDragging(true);
  };

  const handleContainerDragLeave = (event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    if (isDragLeavingContainer(wrapDomContainment(event.currentTarget), event.relatedTarget)) {
      setIsDragging(false);
    }
  };

  const handleContainerDrop = (event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    setIsDragging(false);
    const droppedFile = event.dataTransfer.files?.[0];
    if (droppedFile) {
      void applyFile(droppedFile);
    }
  };

  const handleFileInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      void applyFile(selectedFile);
      event.target.value = '';
    }
  };

  const handleEditorMount: OnMount = (editor, monaco) => {
    const domNode = editor.getDomNode();
    if (domNode && hasFileUploadRef.current) {
      const domContainment = wrapDomContainment(domNode);
      const onDragOver = (event: DragEvent): void => {
        event.preventDefault();
        setIsDragging(true);
      };
      const onDragLeave = (event: DragEvent): void => {
        event.preventDefault();
        if (isDragLeavingContainer(domContainment, event.relatedTarget)) {
          setIsDragging(false);
        }
      };
      const onDrop = (event: DragEvent): void => {
        event.preventDefault();
        event.stopPropagation();
        setIsDragging(false);
        const droppedFile = event.dataTransfer?.files?.[0];
        if (droppedFile) {
          void applyFileRef.current(droppedFile);
        }
      };

      domNode.addEventListener('dragover', onDragOver);
      domNode.addEventListener('dragleave', onDragLeave);
      domNode.addEventListener('drop', onDrop);

      editor.onDidDispose(() => {
        domNode.removeEventListener('dragover', onDragOver);
        domNode.removeEventListener('dragleave', onDragLeave);
        domNode.removeEventListener('drop', onDrop);
      });
    }

    onMount?.(editor, monaco);
  };

  const toolbarVisibility = fileUpload?.toolbarVisibility ?? MonacoFileToolbarVisibility.EMPTY_ONLY;
  const shouldShowToolbar =
    fileUpload !== undefined &&
    !isDragging &&
    (toolbarVisibility === MonacoFileToolbarVisibility.ALWAYS || !value);

  const emptyPromptText =
    fileUpload === undefined
      ? null
      : fileUpload.emptyPrompt === undefined
        ? `Drag & drop or paste ${language.toUpperCase()}`
        : fileUpload.emptyPrompt;

  const uploadButtonLabel = fileUpload?.buttonLabel ?? 'Upload File';

  return (
    <div
      style={height !== undefined ? { height } : undefined}
      aria-labelledby={ariaLabelledBy}
      className={cn(
        'group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card',
        className,
      )}
      onDragOver={hasFileUpload ? handleContainerDragOver : undefined}
      onDragLeave={hasFileUpload ? handleContainerDragLeave : undefined}
      onDrop={hasFileUpload ? handleContainerDrop : undefined}
    >
      {fileError ? (
        <div
          role="alert"
          className="flex shrink-0 items-center justify-between gap-2 border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          <span>{fileError}</span>
          <button
            type="button"
            aria-label="Dismiss file error"
            onClick={() => setFileError(null)}
            className="rounded p-0.5 text-destructive/80 transition-colors hover:bg-destructive/15 hover:text-destructive"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}

      {hasFileUpload && isDragging ? (
        <div className="pointer-events-none absolute inset-0 z-20 m-2 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10 backdrop-blur-xs transition-all duration-150">
          <UploadCloud className="mb-2 h-8 w-8 text-primary" />
          <span className="text-sm font-semibold tracking-tight text-primary">
            Drop file to load
          </span>
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1">
        {!value && !isDragging && cornerPlaceholder ? (
          <div className="pointer-events-none absolute top-3 left-5 z-10 font-mono text-xs whitespace-pre-wrap text-muted-foreground/80">
            {cornerPlaceholder}
          </div>
        ) : null}

        {emptyPromptText && !value && !isDragging ? (
          <div className="pointer-events-none absolute inset-x-0 top-1/3 z-10 flex flex-col items-center gap-1 px-6 text-center">
            <UploadCloud className="mb-1 h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs font-medium text-muted-foreground">{emptyPromptText}</p>
          </div>
        ) : null}

        <Suspense fallback={<Skeleton className="h-full w-full rounded-none" />}>
          <LazyEditor
            height="100%"
            language={language}
            value={value}
            theme={effectiveTheme}
            beforeMount={beforeMount}
            onMount={handleEditorMount}
            onValidate={onValidate}
            onChange={(nextVal) => onChange(nextVal ?? '')}
            options={{
              automaticLayout: true,
              formatOnPaste: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              lineNumbersMinChars: 3,
              wordWrap: 'on',
              folding: true,
              fontSize,
              padding: { top: 12, bottom: 12 },
              renderLineHighlight: 'line',
              hideCursorInOverviewRuler: true,
              overviewRulerBorder: false,
              scrollbar: {
                verticalScrollbarSize: 8,
                horizontalScrollbarSize: 8,
              },
            }}
          />
        </Suspense>
      </div>

      {!fileError && statusBanner ? <div className="shrink-0">{statusBanner}</div> : null}

      {shouldShowToolbar && fileUpload ? (
        <div
          className={cn(
            'flex shrink-0 items-center gap-2 border-t border-border bg-muted/30 px-3 py-1.5',
            toolbarVisibility === MonacoFileToolbarVisibility.ALWAYS
              ? 'justify-between'
              : 'justify-center py-2',
          )}
        >
          <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            {fileUpload.statusText ? (
              <>
                <FileCode2 className="h-3.5 w-3.5 shrink-0 text-primary" />
                <span className="truncate font-mono text-foreground">{fileUpload.statusText}</span>
              </>
            ) : (
              <>
                <UploadCloud className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">
                  {toolbarVisibility === MonacoFileToolbarVisibility.ALWAYS
                    ? 'Drag & drop file or upload'
                    : 'Drag & drop or'}
                </span>
              </>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {fileUpload.extraActions}
            <input
              id={fileInputId}
              type="file"
              accept={fileUpload.accept}
              onChange={handleFileInputChange}
              className="peer sr-only"
            />
            <label
              htmlFor={fileInputId}
              className="inline-flex h-7 cursor-pointer items-center justify-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
            >
              <UploadCloud className="h-3.5 w-3.5" />
              <span>{uploadButtonLabel}</span>
            </label>
          </div>
        </div>
      ) : null}
    </div>
  );
}
