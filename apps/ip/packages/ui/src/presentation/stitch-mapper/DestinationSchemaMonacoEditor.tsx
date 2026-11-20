import { cn, MonacoCodeEditor } from '@soopa/ui';
import { Code2, RotateCcw, UploadCloud } from 'lucide-react';
import React, { useRef, useState } from 'react';
import { toast } from 'sonner';
import { inferSchemaFromSampleJson, type TargetSchemaField } from '../../domain/field-mapping';

export interface DestinationSchemaMonacoEditorProps {
  readonly value: string;
  readonly onChange: (val: string) => void;
  readonly onApply?: (fields: readonly TargetSchemaField[]) => void;
  readonly onClear?: () => void;
  readonly height?: number | string;
  readonly className?: string;
  readonly cornerPlaceholder?: string;
}

/**
 * Reusable Monaco Editor for Destination Schema / Wire Contract.
 * Features:
 * 1. On the editor canvas: "Paste OR Drag & Drop OR Upload" with an interactive Upload button.
 * 2. Native drag & drop file ingestion directly onto the editor.
 * 3. Below the editor: Footer containing strictly only Clear and Format. No description.
 */
export function DestinationSchemaMonacoEditor({
  value,
  onChange,
  onApply,
  onClear,
  height = 320,
  className = '',
  cornerPlaceholder,
}: DestinationSchemaMonacoEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const processFile = (file: File) => {
    if (file.size > 1_048_576) {
      toast.error('File size exceeds 1MB limit.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const content = typeof reader.result === 'string' ? reader.result : '';
      onChange(content);
      const res = inferSchemaFromSampleJson(content);
      if (res.error) {
        toast.error(`Loaded ${file.name}, but JSON syntax is invalid.`);
      } else {
        toast.success(`Loaded ${file.name} (${res.fields.length} wire fields inferred).`);
        onApply?.(res.fields);
      }
    };
    reader.onerror = () => {
      toast.error('Failed to read file.');
    };
    reader.readAsText(file);
  };

  const handleContainerDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleContainerDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const container = containerRef.current;
    if (
      !container ||
      e.relatedTarget === null ||
      (e.relatedTarget instanceof Node && !container.contains(e.relatedTarget))
    ) {
      setIsDragging(false);
    }
  };

  const handleContainerDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      processFile(files[0]);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      processFile(files[0]);
    }
    e.target.value = '';
  };

  const handleFormatJson = () => {
    if (!value || !value.trim()) {
      return;
    }
    try {
      const parsed = JSON.parse(value);
      onChange(JSON.stringify(parsed, null, 2));
      toast.success('JSON formatted.');
    } catch {
      toast.error('Cannot format invalid JSON syntax.');
    }
  };

  const handleClear = () => {
    onChange('');
    onClear?.();
    toast.info('Cleared editor.');
  };

  const hasContent = Boolean(value && value.trim());

  return (
    <div
      ref={containerRef}
      onDragOver={handleContainerDragOver}
      onDragLeave={handleContainerDragLeave}
      onDrop={handleContainerDrop}
      className={cn(
        'group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card',
        className,
      )}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.schema.json"
        onChange={handleFileInputChange}
        className="hidden"
      />

      {/* DRAG-OVERLAY */}
      {isDragging && (
        <div className="pointer-events-none absolute inset-0 z-20 m-2 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10 backdrop-blur-xs transition-all duration-150">
          <UploadCloud className="mb-2 h-8 w-8 text-primary animate-bounce" />
          <span className="text-sm font-semibold tracking-tight text-primary">
            Drop file to load
          </span>
        </div>
      )}

      {/* EDITOR CANVAS AREA */}
      <div className="relative min-h-0 flex-1">
        {/* ON-THE-EDITOR PROMPT: Paste OR Drag & Drop OR Upload (No box) */}
        {!hasContent && !isDragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2.5 px-4 text-center">
            <UploadCloud className="h-8 w-8 text-muted-foreground/40" />
            <div className="flex flex-wrap items-center justify-center gap-2 text-xs font-medium text-muted-foreground">
              <span>Paste</span>
              <span className="text-[11px] font-semibold text-muted-foreground/60 uppercase">
                OR
              </span>
              <span>Drag &amp; Drop</span>
              <span className="text-[11px] font-semibold text-muted-foreground/60 uppercase">
                OR
              </span>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="pointer-events-auto inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-xs hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
              >
                <UploadCloud className="h-3.5 w-3.5" />
                <span>Upload</span>
              </button>
            </div>
          </div>
        )}

        <MonacoCodeEditor
          value={value}
          onChange={onChange}
          language="json"
          height={height}
          fontSize={13}
          cornerPlaceholder={hasContent ? undefined : cornerPlaceholder}
          className="rounded-none border-0"
        />
      </div>

      {/* FOOTER BELOW THE EDITOR: STRICTLY ONLY CLEAR AND FORMAT. NO DESCRIPTION */}
      <div className="flex shrink-0 items-center justify-end gap-1.5 border-t border-border bg-muted/30 px-3 py-1.5">
        <button
          type="button"
          onClick={handleClear}
          className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
        >
          <RotateCcw className="h-3 w-3" />
          <span>Clear</span>
        </button>
        <button
          type="button"
          onClick={handleFormatJson}
          className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
        >
          <Code2 className="h-3 w-3" />
          <span>Format</span>
        </button>
      </div>
    </div>
  );
}
