import Editor from '@monaco-editor/react';
import { Check, Copy } from 'lucide-react';
import { useState } from 'react';
import { registerEdiLanguageAndTheme } from '@/utils/monaco-edi';

interface CodeViewerProps {
  value: string;
  language?: 'edi' | 'json' | 'plaintext';
  className?: string;
  height?: string | number;
}

export function CodeViewer({
  value,
  language = 'json',
  className = '',
  height = '100%',
}: CodeViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleEditorWillMount = (monaco: typeof import('monaco-editor')) => {
    registerEdiLanguageAndTheme(monaco);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  return (
    <div
      className={`relative border border-slate-200 rounded-xl overflow-hidden bg-white ${className} group`}
    >
      <button
        onClick={handleCopy}
        className="absolute bottom-4 right-8 z-50 flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 text-xs font-medium rounded-md opacity-0 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1 transition-opacity shadow-sm"
        title="Copy to clipboard"
      >
        {copied ? (
          <>
            <Check className="w-4 h-4 text-emerald-600" />
            <span className="text-emerald-600">Copied</span>
          </>
        ) : (
          <>
            <Copy className="w-4 h-4" />
            <span>Copy</span>
          </>
        )}
      </button>
      <Editor
        height={height}
        language={language}
        value={value}
        theme="soopa-theme"
        beforeMount={handleEditorWillMount}
        options={{
          readOnly: true,
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
          fontSize: 12,
        }}
      />
    </div>
  );
}
