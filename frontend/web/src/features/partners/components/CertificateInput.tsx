import React, { useState, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { UploadCloud, FileCode, ClipboardPaste } from 'lucide-react';

type CertMode = 'upload' | 'paste';

export interface CertificateInputProps {
  value: string;
  onChange: (pem: string) => void;
}

/**
 * Reusable certificate input with two modes:
 *   - Upload: drag-and-drop or file picker
 *   - Paste: monospace textarea for raw PEM text
 *
 * Stateless regarding the cert value itself — parent owns it.
 */
export function CertificateInput({ value, onChange }: CertificateInputProps) {
  const [mode, setMode] = useState<CertMode>('upload');
  const [isDragging, setIsDragging] = useState(false);
  const [pasteValue, setPasteValue] = useState(value);

  React.useEffect(() => {
    setPasteValue(value);
  }, [value]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      if (content) onChange(content);
    };
    reader.readAsText(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) readFile(e.dataTransfer.files[0]);
  };

  const handlePasteChange = (text: string) => {
    setPasteValue(text);
    onChange(text);
  };

  const handleClear = () => {
    onChange('');
    setPasteValue('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const switchMode = (next: CertMode) => {
    setMode(next);
  };

  return (
    <div className="grid gap-2">
      {/* Tab toggle */}
      <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5 w-fit">
        <button
          type="button"
          onClick={() => switchMode('upload')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${mode === 'upload' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
        >
          <UploadCloud className="h-3.5 w-3.5" />
          Upload
        </button>
        <button
          type="button"
          onClick={() => switchMode('paste')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${mode === 'paste' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
        >
          <ClipboardPaste className="h-3.5 w-3.5" />
          Paste
        </button>
      </div>

      {mode === 'upload' ? (
        <div
          className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 transition-colors ${isDragging ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
          onDrop={handleDrop}
        >
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept=".cer,.crt,.pem,.txt"
            onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])}
          />

          {value ? (
            <div className="flex flex-col items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <FileCode className="h-6 w-6" />
              </div>
              <div className="text-center">
                <span className="block text-sm font-semibold text-slate-700">Certificate Loaded</span>
                <span className="block text-xs text-slate-500 mt-1 truncate max-w-[200px]">
                  {value.substring(0, 30)}...
                </span>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={handleClear}
                className="h-8 text-xs px-3 rounded-lg mt-1 border-slate-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200"
              >
                Replace File
              </Button>
            </div>
          ) : (
            <div
              className="flex flex-col items-center gap-3 text-center cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              tabIndex={0}
              role="button"
            >
              <div className="rounded-full bg-white p-3 shadow-sm border border-slate-100">
                <UploadCloud className="h-6 w-6 text-indigo-500" />
              </div>
              <div>
                <span className="text-sm font-semibold text-indigo-600 hover:underline">Click to upload</span>
                <span className="text-sm text-slate-500"> or drag and drop</span>
              </div>
              <span className="text-xs text-slate-400">PEM, CER, or CRT up to 10MB</span>
            </div>
          )}
        </div>
      ) : (
        <div className="grid gap-1.5">
          <textarea
            className="w-full h-40 rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-700 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 placeholder:text-slate-400"
            placeholder={"-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----"}
            value={pasteValue}
            onChange={(e) => handlePasteChange(e.target.value)}
          />
          {value && (
            <div className="flex items-center gap-2 text-xs text-emerald-600 font-medium">
              <FileCode className="h-3.5 w-3.5" />
              Certificate detected
            </div>
          )}
        </div>
      )}
    </div>
  );
}
