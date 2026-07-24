import Editor from '@monaco-editor/react';
import { useMutation } from '@tanstack/react-query';
import { createRoute } from '@tanstack/react-router';
import axios from 'axios';
import { AlertTriangle, CheckCircle, Copy, FileCode, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { EdiEditorPane } from '@/components/ui/edi-editor-pane';
import { useToast } from '@/hooks/use-toast';
import { registerEdiLanguageAndTheme } from '@/utils/monaco-edi';
import { Route as appRoute } from '../tenant';
import { EdiHumanReadableViewer } from './-components/EdiHumanReadableViewer';

// Simple useDebounce hook for auto-running
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);
    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);
  return debouncedValue;
}

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/edi_tool',
  component: EdiToolPage,
});

export function EdiToolPage() {
  const [inputFormat, setInputFormat] = useState<'EDI' | 'JSON'>('EDI');
  const [outputFormat, setOutputFormat] = useState<'JSON' | 'Human Readable' | 'EDI'>('JSON');

  const [inputPayload, setInputPayload] = useState('');
  const debouncedPayload = useDebounce(inputPayload, 500);

  const [outputResult, setOutputResult] = useState('');
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [isValid, setIsValid] = useState<boolean | null>(null);

  const handleEditorWillMount = (monaco: typeof import('monaco-editor')) => {
    registerEdiLanguageAndTheme(monaco);
  };

  const { toast } = useToast();

  interface TransformResponse {
    valid: boolean;
    result?: string;
    error?: string;
  }

  const transformMutation = useMutation({
    mutationFn: async (variables: { action: string; payload: string }) => {
      const response = await axios.post<TransformResponse>('/api/edi-tools/transform', {
        action: variables.action,
        payload: variables.payload,
      });
      return { data: response.data, variables };
    },
    onSuccess: ({ data, variables }) => {
      const currentAction = inputFormat === 'EDI' ? 'EDI_TO_JSON' : 'JSON_TO_EDI';
      if (variables.payload !== debouncedPayload || variables.action !== currentAction) {
        return; // Ignore stale responses
      }

      setIsValid(data.valid);
      if (data.result) {
        try {
          const parsed = JSON.parse(data.result) as {
            data?: unknown;
            meta?: { validation_errors?: string[] };
          };
          if (parsed.data !== undefined && parsed.meta) {
            setValidationErrors(parsed.meta.validation_errors || []);
            setOutputResult(
              typeof parsed.data === 'string' ? parsed.data : JSON.stringify(parsed.data, null, 2),
            );
          } else {
            setValidationErrors([]);
            setOutputResult(data.result);
          }
        } catch {
          setValidationErrors([]);
          setOutputResult(data.result);
        }
      } else if (!data.valid) {
        setValidationErrors([]);
        setOutputResult(data.error || 'Unknown error occurred.');
      } else {
        setValidationErrors([]);
        setOutputResult('Valid format.');
      }
    },
    onError: (
      error: Error | import('axios').AxiosError,
      variables: { action: string; payload: string },
    ) => {
      const currentAction = inputFormat === 'EDI' ? 'EDI_TO_JSON' : 'JSON_TO_EDI';
      if (variables.payload !== debouncedPayload || variables.action !== currentAction) {
        return; // Ignore stale error responses
      }

      setValidationErrors([]);
      setIsValid(false);

      let errorDetail =
        ('response' in error ? (error.response?.data as { detail?: string })?.detail : undefined) ||
        error.message;
      if (typeof errorDetail !== 'string') {
        errorDetail = JSON.stringify(errorDetail);
      }
      setOutputResult(errorDetail);
      toast({
        title: 'API Error',
        description: 'Failed to communicate with the testing endpoint.',
        variant: 'destructive',
      });
    },
  });

  // Auto-run transformation when debounced payload or input format changes
  useEffect(() => {
    if (debouncedPayload.trim()) {
      transformMutation.mutate({
        action: inputFormat === 'EDI' ? 'EDI_TO_JSON' : 'JSON_TO_EDI',
        payload: debouncedPayload,
      });
    } else {
      setOutputResult('');
      setValidationErrors([]);
      setIsValid(null);
    }
  }, [debouncedPayload, inputFormat]);

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

  const renderOutputPane = () => {
    if (outputFormat === 'Human Readable') {
      try {
        const sourceData = inputFormat === 'JSON' ? inputPayload : outputResult;
        if (!sourceData) return <div className="p-4 text-slate-500">No data to display.</div>;

        const parsedData = JSON.parse(sourceData) as {
          data?: unknown;
          meta?: { validation_errors?: string[] };
        };

        let astToRender = parsedData;
        let errorsToRender = validationErrors;

        // Smart Extractor: If the user pasted an API Envelope, extract the pristine data and errors
        if (inputFormat === 'JSON' && parsedData.data) {
          astToRender = parsedData.data;
          if (parsedData.meta && parsedData.meta.validation_errors) {
            errorsToRender = parsedData.meta.validation_errors;
          }
        }

        return <EdiHumanReadableViewer data={astToRender} validationErrors={errorsToRender} />;
      } catch {
        return (
          <div className="p-4 text-red-500 font-medium">
            Could not parse JSON for human-readable viewing.
          </div>
        );
      }
    }

    return (
      <div className="flex flex-col h-full relative">
        {validationErrors.length > 0 && (
          <div className="bg-red-50 border-b border-red-200 p-3 shrink-0">
            <div className="flex items-center gap-2 text-red-800 font-bold text-sm mb-2">
              <AlertTriangle className="w-4 h-4" />
              Validation Errors
            </div>
            <ul className="list-disc list-inside text-red-600 text-xs font-medium space-y-1 overflow-y-auto max-h-32">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language={outputFormat === 'EDI' ? 'edi' : 'json'}
            value={outputResult}
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
            }}
          />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4 flex flex-col h-[calc(100vh-8rem)]">
      <style>{`
        /* Force span tokens inside the lines to adopt our custom colors */
      `}</style>
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
          <FileCode className="w-6 h-6 text-indigo-600" />
          EDI Tool
        </h2>
      </div>

      <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
        {/* Left Pane (Input) */}
        <div className="flex flex-col border rounded-xl bg-white shadow-sm overflow-hidden relative">
          <div className="bg-slate-50 px-4 py-2 border-b flex items-center justify-between">
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-md border">
              <button
                onClick={() => {
                  setInputFormat('EDI');
                  setOutputFormat('JSON');
                }}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  inputFormat === 'EDI'
                    ? 'bg-purple-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-purple-700 hover:bg-purple-50'
                }`}
              >
                EDI Input
              </button>
              <button
                onClick={() => {
                  setInputFormat('JSON');
                  setOutputFormat('EDI');
                }}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  inputFormat === 'JSON'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-blue-700 hover:bg-blue-50'
                }`}
              >
                JSON Input
              </button>
            </div>

            <div className="flex items-center gap-1">
              {transformMutation.isPending && (
                <span className="text-xs text-slate-400 font-medium mr-2 animate-pulse">
                  Processing...
                </span>
              )}
              <button
                onClick={() => setInputPayload('')}
                className="p-1.5 hover:bg-slate-200 rounded text-slate-500 hover:text-red-600 transition-colors flex items-center justify-center"
                title="Clear Input"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => handleCopy(inputPayload, 'Input')}
                className="p-1.5 hover:bg-slate-200 rounded text-slate-500 transition-colors flex items-center justify-center"
                title="Copy Input"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>
          <EdiEditorPane
            value={inputPayload}
            onChange={(value) => {
              // Auto-detect if user pasted full JSON while in EDI mode
              if (inputFormat === 'EDI' && value.trim().startsWith('{')) {
                try {
                  JSON.parse(value);
                  setInputFormat('JSON');
                  setOutputFormat('EDI');
                } catch {
                  // Not valid JSON yet, do nothing
                }
              }
              setInputPayload(value);
            }}
            language={inputFormat === 'EDI' ? 'edi' : 'json'}
          />
        </div>

        {/* Right Pane (Output) */}
        <div className="flex flex-col border rounded-xl bg-white shadow-sm overflow-hidden relative">
          <div className="bg-slate-50 px-4 py-2 border-b flex items-center justify-between">
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-md border">
              <button
                onClick={() => setOutputFormat('Human Readable')}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  outputFormat === 'Human Readable'
                    ? 'bg-slate-700 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                Human Readable
              </button>

              {inputFormat === 'EDI' ? (
                <button
                  onClick={() => setOutputFormat('JSON')}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    outputFormat === 'JSON'
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-slate-600 hover:text-blue-700 hover:bg-blue-50'
                  }`}
                >
                  JSON Output
                </button>
              ) : (
                <button
                  onClick={() => setOutputFormat('EDI')}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    outputFormat === 'EDI'
                      ? 'bg-purple-600 text-white shadow-sm'
                      : 'text-slate-600 hover:text-purple-700 hover:bg-purple-50'
                  }`}
                >
                  EDI Output
                </button>
              )}
            </div>

            <div className="flex items-center gap-3">
              {isValid === true && (
                <div className="flex items-center gap-1.5 text-green-600 bg-green-50 px-2 py-0.5 rounded-full border border-green-200 shadow-sm">
                  <CheckCircle className="w-4 h-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">Success</span>
                </div>
              )}
              {isValid === false && (
                <div className="flex items-center gap-1.5 text-red-600 bg-red-50 px-2 py-0.5 rounded-full border border-red-200 shadow-sm">
                  <AlertTriangle className="w-4 h-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">Error</span>
                </div>
              )}
              <div className="flex items-center gap-1 border-l border-slate-200 pl-3">
                <button
                  onClick={() => setInputPayload('')}
                  className="p-1.5 hover:bg-slate-200 rounded text-slate-500 hover:text-red-600 transition-colors flex items-center justify-center"
                  title="Clear All"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleCopy(outputResult, 'Output')}
                  className="p-1.5 hover:bg-slate-200 rounded text-slate-500 transition-colors flex items-center justify-center"
                  title="Copy Output"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
          <div className="flex-1 p-0 bg-white min-h-0 flex flex-col">{renderOutputPane()}</div>
        </div>
      </div>
    </div>
  );
}
