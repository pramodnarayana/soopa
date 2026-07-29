import Editor from '@monaco-editor/react';
import { UploadCloud } from 'lucide-react';
import React, { useState } from 'react';
import { registerEdiLanguageAndTheme } from '../../utils/monaco-edi';

export interface EdiEditorPaneProps {
  value: string;
  onChange: (value: string) => void;
  language?: 'edi' | 'json' | 'plaintext';
  placeholder?: string;
  cornerPlaceholder?: string;
  className?: string;
  acceptedFileExtensions?: string;
  extraActions?: React.ReactNode;
  fontSize?: number;
  showCertDetected?: boolean;
  /** When false, suppresses the big "Drag and drop" heading. Buttons are always shown. */
  showEmptyState?: boolean;
}

export function EdiEditorPane({
  value,
  onChange,
  language = 'edi',
  placeholder,
  cornerPlaceholder,
  className = '',
  acceptedFileExtensions = '.edi,.json,.txt,.x12',
  extraActions,
  fontSize = 13,
  showCertDetected = false,
  showEmptyState = true,
}: EdiEditorPaneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const applyFile = async (file: File) => {
    setError(null);
    if (file.size > 1024 * 1024) {
      setError('File size exceeds 1MB limit. Please upload a smaller file.');
      return;
    }
    try {
      const text = await file.text();
      onChange(text);
    } catch (err) {
      setError(`Failed to read file: ${(err as Error).message}`);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await applyFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await applyFile(e.target.files[0]);
      e.target.value = '';
    }
  };

  const handleEditorWillMount = (monaco: typeof import('monaco-editor')) => {
    registerEdiLanguageAndTheme(monaco);
  };

  // Monaco's content area intercepts drag events, so we attach listeners
  // directly to its DOM node to ensure drag-and-drop always works.
  const handleEditorMount = (editor: import('monaco-editor').editor.IStandaloneCodeEditor) => {
    const domNode = editor.getDomNode();
    if (!domNode) return;

    const onDragOver = (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(true);
    };
    const onDragLeave = (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        void applyFile(e.dataTransfer.files[0]);
      }
    };

    domNode.addEventListener('dragover', onDragOver);
    domNode.addEventListener('dragleave', onDragLeave);
    domNode.addEventListener('drop', onDrop);

    // Cleanup handled via Monaco's own disposal lifecycle
    editor.onDidDispose(() => {
      domNode.removeEventListener('dragover', onDragOver);
      domNode.removeEventListener('dragleave', onDragLeave);
      domNode.removeEventListener('drop', onDrop);
    });
  };

  return (
    <div
      className={`flex-1 p-0 bg-white min-h-[250px] flex flex-col relative group ${className}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Error banner */}
      {error && (
        <div className="absolute top-2 right-2 left-2 z-30 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-md shadow-sm flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-red-500 hover:text-red-700 font-bold ml-4"
          >
            ×
          </button>
        </div>
      )}

      {/* Certificate detected — bottom status bar (when value present) */}
      {!error &&
        value &&
        showCertDetected &&
        value.includes('-----BEGIN CERTIFICATE-----') &&
        value.includes('-----END CERTIFICATE-----') && (
          <div className="absolute bottom-0 left-0 right-0 z-30 px-4 py-2 bg-green-50 border-t border-green-200 text-green-700 text-xs font-semibold flex items-center gap-2 pointer-events-none">
            <svg
              className="w-3.5 h-3.5 shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
            Certificate detected — ready to save
          </div>
        )}

      {/* Drag-over full-screen overlay */}
      {isDragging && (
        <div className="absolute inset-0 bg-indigo-50/90 z-20 flex flex-col items-center justify-center border-2 border-indigo-400 border-dashed m-2 rounded-lg backdrop-blur-sm transition-all duration-200 pointer-events-none">
          <UploadCloud className="w-10 h-10 text-indigo-500 mb-3 animate-bounce" />
          <span className="text-indigo-700 font-semibold text-lg tracking-tight">
            Drop file to load
          </span>
        </div>
      )}

      {/* Corner placeholder (e.g. PEM hint) */}
      {!value && !isDragging && cornerPlaceholder && (
        <div className="absolute top-4 left-6 z-10 text-xs text-slate-400 font-mono text-left whitespace-pre-wrap pointer-events-none opacity-90">
          {cornerPlaceholder}
        </div>
      )}

      {/* Optional "Drag and drop" heading for the EDI editor */}
      {showEmptyState && !value && !isDragging && (
        <div className="absolute inset-x-0 top-1/3 z-10 flex flex-col items-center gap-1 pointer-events-none text-center px-6">
          <UploadCloud className="w-10 h-10 text-slate-150 mb-1" />
          <p className="text-sm font-medium text-slate-400">
            {placeholder || `Drag & drop or paste ${language.toUpperCase()}`}
          </p>
        </div>
      )}

      {/* Monaco editor — always rendered */}
      <Editor
        height="100%"
        language={language}
        value={value}
        onChange={(val) => onChange(val || '')}
        theme="soopa-theme"
        beforeMount={handleEditorWillMount}
        onMount={handleEditorMount}
        options={{
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          lineNumbersMinChars: 3,
          wordWrap: 'on',
          folding: true,
          fontSize,
          padding: { top: 16, bottom: 16 },
          renderLineHighlight: 'none',
          hideCursorInOverviewRuler: true,
          overviewRulerBorder: false,
          scrollbar: {
            verticalScrollbarSize: 8,
            horizontalScrollbarSize: 8,
          },
        }}
      />

      {/* Bottom toolbar — always shown when editor is empty, sits below Monaco */}
      {!value && !isDragging && (
        <div className="absolute bottom-0 left-0 right-0 z-10 flex items-center justify-center gap-3 px-4 py-2.5 bg-white/90 backdrop-blur-sm border-t border-slate-100">
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <UploadCloud className="w-3 h-3" />
            Drag &amp; drop or
          </span>
          <label className="cursor-pointer inline-flex items-center justify-center px-3 py-1.5 border border-transparent text-xs font-semibold rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 transition-colors">
            <UploadCloud className="w-3.5 h-3.5 mr-1.5" />
            Upload File
            <input
              type="file"
              className="hidden"
              accept={acceptedFileExtensions}
              onChange={handleFileUpload}
            />
          </label>
          {extraActions}
        </div>
      )}
    </div>
  );
}
