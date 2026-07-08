import React, { useState } from 'react';
import Editor from '@monaco-editor/react';
import { UploadCloud } from 'lucide-react';
import { registerEdiLanguageAndTheme } from '@/utils/monaco-edi';

export interface EdiEditorPaneProps {
  value: string;
  onChange: (value: string) => void;
  language?: 'edi' | 'json' | 'plaintext';
  placeholder?: string;
  cornerPlaceholder?: string;
  className?: string;
  acceptedFileExtensions?: string;
}

export function EdiEditorPane({ value, onChange, language = 'edi', placeholder, cornerPlaceholder, className = '', acceptedFileExtensions = ".edi,.json,.txt,.x12" }: EdiEditorPaneProps) {
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

  const handleEditorWillMount = (monaco: any) => {
    registerEdiLanguageAndTheme(monaco);
  };

  return (
    <div
      className={`flex-1 p-0 bg-white min-h-[250px] flex flex-col relative group ${className}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {error && (
        <div className="absolute top-2 right-2 left-2 z-30 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-md shadow-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700 font-bold ml-4">
            ×
          </button>
        </div>
      )}
      {isDragging && (
        <div className="absolute inset-0 bg-indigo-50/90 z-20 flex flex-col items-center justify-center border-2 border-indigo-400 border-dashed m-2 rounded-lg backdrop-blur-sm transition-all duration-200">
          <UploadCloud className="w-10 h-10 text-indigo-500 mb-3 animate-bounce" />
          <span className="text-indigo-700 font-semibold text-lg tracking-tight">Drop file to load</span>
        </div>
      )}
      {!value && !isDragging && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center p-6 text-center pointer-events-none">
          {cornerPlaceholder && (
            <div className="absolute top-4 left-6 text-xs text-slate-400 font-mono text-left whitespace-pre-wrap pointer-events-none opacity-90">
              {cornerPlaceholder}
            </div>
          )}
          <UploadCloud className="w-12 h-12 text-slate-200 mb-4" />
          <h3 className="text-lg font-medium text-slate-900 mb-1">Drag and drop your file here</h3>
          <p className="text-sm text-slate-500 mb-6">{placeholder || `or upload a file, or click anywhere to paste raw ${language.toUpperCase()}`}</p>
          <label className="pointer-events-auto cursor-pointer inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 transition-colors">
            Upload File
            <input type="file" className="hidden" accept={acceptedFileExtensions} onChange={handleFileUpload} />
          </label>
        </div>
      )}

      <Editor
        height="100%"
        language={language}
        value={value}
        onChange={(val) => onChange(val || '')}
        theme="soopa-theme"
        beforeMount={handleEditorWillMount}
        options={{
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          lineNumbersMinChars: 3,
          wordWrap: 'on',
          folding: true,
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
    </div>
  );
}
