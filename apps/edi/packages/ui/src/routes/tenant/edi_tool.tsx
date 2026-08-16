import Editor from '@monaco-editor/react';
import { useMutation } from '@tanstack/react-query';
import { createRoute } from '@tanstack/react-router';

import { AlertTriangle, CheckCircle, Copy, FileCode, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { EdiEditorPane } from '../../components/ui/edi-editor-pane';
import { useUcpNetwork } from '../../contexts/UcpNetworkContext';
import { useToast } from '../../hooks/use-toast';
import { registerEdiLanguageAndTheme } from '../../utils/monaco-edi';
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

interface TransformResponse {
  valid: boolean;
  result?: string;
  error?: string;
}

interface ProcessResultPayload {
  data: TransformResponse;
  variables: { payload: string; action: string };
  debouncedPayload: string;
  currentAction: string;
}

function _parseTransformSuccessResult(data: TransformResponse): {
  outputResult: string;
  validationErrors: string[];
} {
  if (!data.result) {
    let parsedErrors: string[] = [];
    if (data.error) {
      try {
        const parsedError = JSON.parse(data.error);
        if (parsedError.errors && Array.isArray(parsedError.errors)) {
          parsedErrors = parsedError.errors;
        }
      } catch {
        // Ignore parse errors on the error string
      }
    }
    return {
      outputResult: data.valid ? 'Valid format.' : data.error || 'Unknown error occurred.',
      validationErrors: parsedErrors,
    };
  }

  try {
    const parsed = JSON.parse(data.result) as {
      data?: unknown;
      meta?: { validation_errors?: string[] };
    };

    console.log('EDI Tool Debug: Parsed Backend Response:', parsed);

    if (parsed.data !== undefined && parsed.meta) {
      const resultString =
        typeof parsed.data === 'string' ? parsed.data : JSON.stringify(parsed.data, null, 2);
      console.log('EDI Tool Debug: Returning outputResult of length:', resultString.length);
      return {
        outputResult: resultString,
        validationErrors: parsed.meta.validation_errors || [],
      };
    }
  } catch (err) {
    console.warn('EDI Tool Debug: JSON.parse failed:', err);
    // Ignore JSON parse errors and return raw result
  }

  return { outputResult: data.result, validationErrors: [] };
}

function processTransformSuccess({
  data,
  variables,
  debouncedPayload,
  currentAction,
}: ProcessResultPayload): {
  ignored: boolean;
  isValid: boolean | null;
  validationErrors: string[];
  outputResult: string;
} {
  if (variables.payload !== debouncedPayload || variables.action !== currentAction) {
    return { ignored: true, isValid: null, validationErrors: [], outputResult: '' };
  }

  const { outputResult, validationErrors } = _parseTransformSuccessResult(data);
  return { ignored: false, isValid: data.valid, validationErrors, outputResult };
}

const FormatToggleButton = ({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) => (
  <button
    onClick={onClick}
    className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all duration-150 ${
      active
        ? 'bg-background shadow-sm text-foreground border border-border/60'
        : 'text-muted-foreground hover:text-foreground'
    }`}
  >
    {children}
  </button>
);

const EdiHumanReadableContainer = ({
  inputFormat,
  inputPayload,
  outputResult,
  validationErrors,
}: {
  inputFormat: 'EDI' | 'JSON';
  inputPayload: string;
  outputResult: string;
  validationErrors: string[];
}) => {
  try {
    const sourceData = inputFormat === 'JSON' ? inputPayload : outputResult;
    if (!sourceData) return <div className="p-4 text-slate-500">No data to display.</div>;

    const parsedData = JSON.parse(sourceData) as {
      data?: unknown;
      meta?: { validation_errors?: string[] };
    };

    let astToRender = parsedData;
    let errorsToRender = validationErrors;

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
};

const EdiCodeViewer = ({
  outputFormat,
  outputResult,
  validationErrors,
  onEditorWillMount,
}: {
  outputFormat: 'JSON' | 'EDI';
  outputResult: string;
  validationErrors: string[];
  onEditorWillMount: (monaco: typeof import('monaco-editor')) => void;
}) => (
  <div className="flex flex-col w-full h-full relative">
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
        beforeMount={onEditorWillMount}
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

const EdiOutputViewer = ({
  outputFormat,
  inputFormat,
  inputPayload,
  outputResult,
  validationErrors,
  onEditorWillMount,
}: {
  outputFormat: 'JSON' | 'Human Readable' | 'EDI';
  inputFormat: 'EDI' | 'JSON';
  inputPayload: string;
  outputResult: string;
  validationErrors: string[];
  onEditorWillMount: (monaco: typeof import('monaco-editor')) => void;
}) => {
  if (outputFormat === 'Human Readable') {
    return (
      <EdiHumanReadableContainer
        inputFormat={inputFormat}
        inputPayload={inputPayload}
        outputResult={outputResult}
        validationErrors={validationErrors}
      />
    );
  }

  return (
    <EdiCodeViewer
      outputFormat={outputFormat}
      outputResult={outputResult}
      validationErrors={validationErrors}
      onEditorWillMount={onEditorWillMount}
    />
  );
};

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

  const api = useUcpNetwork();

  interface TransformResponse {
    valid: boolean;
    result?: string;
    error?: string;
  }

  const transformMutation = useMutation({
    mutationFn: async (variables: { action: string; payload: string }) => {
      const response = await api.post<TransformResponse>('/edi-tools/transform', {
        action: variables.action,
        payload: variables.payload,
      });
      return { data: response.data, variables };
    },
    onSuccess: ({ data, variables }) => {
      const currentAction = inputFormat === 'EDI' ? 'EDI_TO_JSON' : 'JSON_TO_EDI';
      const res = processTransformSuccess({ data, variables, debouncedPayload, currentAction });

      if (res.ignored) return;

      setIsValid(res.isValid);
      setValidationErrors(res.validationErrors);
      setOutputResult(res.outputResult);
    },
    onError: (error: Error, variables: { action: string; payload: string }) => {
      const currentAction = inputFormat === 'EDI' ? 'EDI_TO_JSON' : 'JSON_TO_EDI';
      if (variables.payload !== debouncedPayload || variables.action !== currentAction) {
        return; // Ignore stale error responses
      }

      setValidationErrors([]);
      setIsValid(false);

      let errorDetail = error.message;
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

  // EdiOutputViewer component extracted

  return (
    <div className="space-y-4 flex flex-col h-[calc(100vh-8rem)]">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <h2 className="text-3xl font-extrabold tracking-tight text-foreground flex items-center gap-3">
            <FileCode className="w-7 h-7 text-primary" />
            EDI Tool
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Paste EDI or JSON to instantly validate and transform between formats.
          </p>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
        {/* Left Pane (Input) */}
        <div className="flex flex-col border border-border rounded-xl bg-card shadow-sm overflow-hidden">
          <div className="bg-muted/50 px-4 py-2.5 border-b border-border flex items-center justify-between shrink-0">
            <div className="flex items-center gap-1 bg-muted p-1 rounded-lg border border-border/40">
              <FormatToggleButton
                active={inputFormat === 'EDI'}
                onClick={() => {
                  setInputFormat('EDI');
                  setOutputFormat('JSON');
                }}
              >
                EDI Input
              </FormatToggleButton>
              <FormatToggleButton
                active={inputFormat === 'JSON'}
                onClick={() => {
                  setInputFormat('JSON');
                  setOutputFormat('EDI');
                }}
              >
                JSON Input
              </FormatToggleButton>
            </div>

            <div className="flex items-center gap-1">
              {transformMutation.isPending && (
                <span className="text-xs text-muted-foreground font-medium mr-2 animate-pulse">
                  Processing...
                </span>
              )}
              <button
                onClick={() => setInputPayload('')}
                className="p-1.5 hover:bg-muted rounded-md text-muted-foreground hover:text-destructive transition-colors flex items-center justify-center"
                title="Clear Input"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => handleCopy(inputPayload, 'Input')}
                className="p-1.5 hover:bg-muted rounded-md text-muted-foreground hover:text-foreground transition-colors flex items-center justify-center"
                title="Copy Input"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>
          <EdiEditorPane
            value={inputPayload}
            onChange={(value: string | undefined) => {
              // Auto-detect if user pasted full JSON while in EDI mode
              if (value && inputFormat === 'EDI' && value.trim().startsWith('{')) {
                try {
                  JSON.parse(value);
                  setInputFormat('JSON');
                  setOutputFormat('EDI');
                } catch {
                  // Not valid JSON yet, do nothing
                }
              }
              setInputPayload(value || '');
            }}
            language={inputFormat === 'EDI' ? 'edi' : 'json'}
          />
        </div>

        {/* Right Pane (Output) */}
        <div className="flex flex-col border border-border rounded-xl bg-card shadow-sm overflow-hidden">
          <div className="bg-muted/50 px-4 py-2.5 border-b border-border flex items-center justify-between shrink-0">
            <div className="flex items-center gap-1 bg-muted p-1 rounded-lg border border-border/40">
              <FormatToggleButton
                active={outputFormat === 'Human Readable'}
                onClick={() => setOutputFormat('Human Readable')}
              >
                Human Readable
              </FormatToggleButton>

              {inputFormat === 'EDI' ? (
                <FormatToggleButton
                  active={outputFormat === 'JSON'}
                  onClick={() => setOutputFormat('JSON')}
                >
                  JSON Output
                </FormatToggleButton>
              ) : (
                <FormatToggleButton
                  active={outputFormat === 'EDI'}
                  onClick={() => setOutputFormat('EDI')}
                >
                  EDI Output
                </FormatToggleButton>
              )}
            </div>

            <div className="flex items-center gap-3">
              {isValid === true && (
                <div className="flex items-center gap-1.5 text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200">
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span className="text-xs font-bold uppercase tracking-wider">Valid</span>
                </div>
              )}
              {isValid === false && (
                <div className="flex items-center gap-1.5 text-destructive bg-destructive/10 px-2.5 py-1 rounded-full border border-destructive/20">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span className="text-xs font-bold uppercase tracking-wider">Error</span>
                </div>
              )}
              <div className="flex items-center gap-1 border-l border-border pl-3">
                <button
                  onClick={() => setInputPayload('')}
                  className="p-1.5 hover:bg-muted rounded-md text-muted-foreground hover:text-destructive transition-colors flex items-center justify-center"
                  title="Clear All"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleCopy(outputResult, 'Output')}
                  className="p-1.5 hover:bg-muted rounded-md text-muted-foreground hover:text-foreground transition-colors flex items-center justify-center"
                  title="Copy Output"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
          <div className="flex-1 p-0 bg-card min-h-0 flex flex-col">
            <EdiOutputViewer
              outputFormat={outputFormat}
              inputFormat={inputFormat}
              inputPayload={inputPayload}
              outputResult={outputResult}
              validationErrors={validationErrors}
              onEditorWillMount={handleEditorWillMount}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
