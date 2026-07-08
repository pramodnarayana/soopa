import { useState } from 'react';
import Editor from '@monaco-editor/react';
import { UploadCloud } from 'lucide-react';

export interface EdiEditorPaneProps {
  value: string;
  onChange: (value: string) => void;
  language?: 'edi' | 'json' | 'plaintext';
  placeholder?: string;
  cornerPlaceholder?: string;
  className?: string;
}

export function EdiEditorPane({ value, onChange, language = 'edi', placeholder, cornerPlaceholder, className = '' }: EdiEditorPaneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const applyFile = async (file: File) => {
    const text = await file.text();
    onChange(text);
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
    if (!monaco.languages.getLanguages().some((l: any) => l.id === 'edi')) {
      monaco.languages.register({ id: 'edi' });
      monaco.languages.setMonarchTokensProvider('edi', {
        tokenizer: {
          root: [
            [/^[A-Z0-9]{2,3}(?=\*)/, 'keyword'],
            [/(~\s*)([A-Z0-9]{2,3})(?=\*)/, ['delimiter', 'keyword']],
            [/\*/, 'delimiter'],
            [/~/, 'delimiter'],
            [/[^*~\n\r]+/, 'string'],
          ],
        },
      });
    }
    monaco.editor.defineTheme('soopa-theme', {
      base: 'vs',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: '0451a5', fontStyle: 'bold' },
        { token: 'string', foreground: '065f46' },
        { token: 'delimiter', foreground: '000000' },
        { token: 'string.key.json', foreground: '0451a5', fontStyle: 'bold' },
        { token: 'string.value.json', foreground: '065f46' },
        { token: 'number.json', foreground: '065f46' },
        { token: 'keyword.json', foreground: '0451a5', fontStyle: 'bold' },
      ],
      colors: {
        'editor.background': '#ffffff',
      }
    });
  };

  return (
    <div
      className={`flex-1 p-0 bg-white min-h-[250px] flex flex-col relative group ${className}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
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
            <input type="file" className="hidden" accept=".edi,.json,.txt,.x12" onChange={handleFileUpload} />
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
