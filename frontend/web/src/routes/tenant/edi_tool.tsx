import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import axios from 'axios';
import { FileCode, CheckCircle, AlertTriangle, Copy } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import Editor, { useMonaco } from '@monaco-editor/react';
import { useEffect } from 'react';

import { createRoute } from '@tanstack/react-router';
import { Route as appRoute } from '../tenant';

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/edi_tool',
  component: EditTester,
});

function EditTester() {
  const monaco = useMonaco();
  const [action, setAction] = useState('EDI_TO_JSON');
  const [inputPayload, setInputPayload] = useState('');
  const [outputResult, setOutputResult] = useState('');
  const [isValid, setIsValid] = useState<boolean | null>(null);

  useEffect(() => {
    if (monaco) {
      monaco.languages.register({ id: 'edi' });
      monaco.languages.setMonarchTokensProvider('edi', {
        tokenizer: {
          root: [
            // Match segment IDs at the start of a line
            [/^[A-Z0-9]{2,3}(?=\*)/, 'keyword'],

            // Match segment IDs that immediately follow a tilde (and optional whitespace)
            [/(~\s*)([A-Z0-9]{2,3})(?=\*)/, ['delimiter', 'keyword']],

            // Delimiters
            [/\*/, 'delimiter'],
            [/~/, 'delimiter'],

            // Data Elements
            [/[^*~\n\r]+/, 'string'],
          ],
        },
      });
    }
  }, [monaco]);

  const { toast } = useToast();

  const transformMutation = useMutation({
    mutationFn: async () => {
      const response = await axios.post('/api/edi-tools/transform', {
        action,
        payload: inputPayload,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setIsValid(data.valid);
      if (data.valid) {
        if (data.result) {
          setOutputResult(data.result);
        } else {
          setOutputResult('Valid format.');
        }

      } else {
        setOutputResult(data.error || 'Unknown error occurred.');

      }
    },
    onError: (error: any) => {
      setIsValid(false);
      setOutputResult(error.response?.data?.detail || error.message);
      toast({
        title: 'API Error',
        description: 'Failed to communicate with the testing endpoint.',
        variant: 'destructive',
      });
    },
  });

  const getLanguage = (pane: 'input' | 'output') => {
    if (pane === 'input') {
      return action === 'JSON_TO_EDI' ? 'json' : 'edi';
    }
    return action === 'JSON_TO_EDI' ? 'edi' : 'json';
  };

  const handleCopy = async (text: string, paneName: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast({
        title: 'Copied',
        description: `${paneName} copied to clipboard.`,
      });
    } catch {
      toast({
        title: 'Error',
        description: 'Failed to copy to clipboard.',
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="space-y-6 flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <FileCode className="w-6 h-6 text-indigo-600" />
            EDI Tool
          </h2>
        </div>
        <div className="flex items-center gap-3 bg-white p-2 rounded-lg border shadow-sm">
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOutputResult('');
              setIsValid(null);
            }}
            className="text-sm border-slate-200 rounded-md bg-slate-50 py-1.5 px-3 focus:ring-indigo-500"
          >
            <option value="EDI_TO_JSON">EDI to JSON</option>
            <option value="JSON_TO_EDI">JSON to EDI</option>
          </select>
          <Button
            onClick={() => transformMutation.mutate()}
            disabled={transformMutation.isPending || !inputPayload.trim()}
            className="bg-indigo-600 hover:bg-indigo-700"
          >
            {transformMutation.isPending ? 'Processing...' : 'Run'}
          </Button>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
        {/* Left Pane */}
        <div className="flex flex-col border rounded-xl bg-white shadow-sm overflow-hidden">
          <div className="bg-slate-50 px-4 py-2 border-b flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Input</span>
            <button
              onClick={() => handleCopy(inputPayload, 'Input')}
              className="p-1 hover:bg-slate-200 rounded text-slate-500 transition-colors"
              title="Copy Input"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 p-0 bg-white min-h-0 flex flex-col">
            <Editor
              height="100%"
              language={getLanguage('input')}
              value={inputPayload}
              onChange={(val) => setInputPayload(val || '')}
              theme="light"
              options={{
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
        </div>

        {/* Right Pane */}
        <div className="flex flex-col border rounded-xl bg-white shadow-sm overflow-hidden relative">
          <div className="bg-slate-50 px-4 py-2 border-b flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Output</span>
            <div className="flex items-center gap-3">
              {isValid === true && <CheckCircle className="w-4 h-4 text-green-500" />}
              {isValid === false && <AlertTriangle className="w-4 h-4 text-red-500" />}
              <button
                onClick={() => handleCopy(outputResult, 'Output')}
                className="p-1 hover:bg-slate-200 rounded text-slate-500 transition-colors"
                title="Copy Output"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 p-0 bg-white min-h-0 flex flex-col">
            <Editor
              height="100%"
              language={getLanguage('output')}
              value={outputResult}
              theme="light"
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
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
