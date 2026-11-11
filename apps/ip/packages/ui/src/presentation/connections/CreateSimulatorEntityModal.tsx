import {
  type ApiProblem,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  MonacoCodeEditor,
  MonacoFileToolbarVisibility,
} from '@soopa/ui';
import { Braces } from 'lucide-react';
import React, { useId, useState } from 'react';
import { toast } from 'sonner';
import { useUpdateConnectionMutation } from '../../application/use-connection-queries';
import {
  buildPublicConfigWithSimulatorStream,
  type Connection,
  clampSimulatorRecordsPerPull,
  SIMULATOR_STREAM_LIMITS,
  type SimulatorBlueprintJson,
} from '../../domain/connection';
import type { JsonRecord } from '../../domain/enums';

export interface CreateSimulatorEntityModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onEntityCreated?: (entityName: string) => void;
}

export interface CreateSimulatorEntityFormProps {
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onCancel: () => void;
  readonly onEntityCreated?: (entityName: string) => void;
}

export interface ParsedSimulatorBlueprintSuccess {
  readonly ok: true;
  readonly formatted: string;
  readonly parsed: SimulatorBlueprintJson;
}

export interface ParsedSimulatorBlueprintFailure {
  readonly ok: false;
  readonly reason: string;
}

export type ParsedSimulatorBlueprintOutcome =
  | ParsedSimulatorBlueprintSuccess
  | ParsedSimulatorBlueprintFailure;

const DEFAULT_SAMPLE_JSON = `{
  "order_id": "ORD-1001",
  "customer_email": "buyer@example.org",
  "total_amount": 249.50,
  "status": "CREATED",
  "updated_at": "2026-11-10T10:00:00Z"
}`;

function isSimulatorBlueprintJson(value: unknown): value is SimulatorBlueprintJson {
  if (Array.isArray(value)) {
    return true;
  }
  return typeof value === 'object' && value !== null;
}

export function inferSimulatorEntityNameFromFilename(fileName: string): string {
  return fileName
    .replace(/\.schema\.json$/i, '')
    .replace(/\.json$/i, '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function parseSimulatorBlueprint(
  rawText: string,
  fileName?: string,
): ParsedSimulatorBlueprintOutcome {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawText);
  } catch {
    return {
      ok: false,
      reason: fileName
        ? `File "${fileName}" is not valid JSON.`
        : 'Uploaded or pasted JSON is invalid. Please provide a valid JSON object or schema.',
    };
  }

  if (!isSimulatorBlueprintJson(parsed)) {
    return {
      ok: false,
      reason: 'JSON blueprint must be a JSON object or array of sample objects.',
    };
  }

  const normalizedBlueprint: SimulatorBlueprintJson = Array.isArray(parsed)
    ? (parsed as readonly unknown[])
    : (parsed as JsonRecord);

  return {
    ok: true,
    formatted: JSON.stringify(normalizedBlueprint, null, 2),
    parsed: normalizedBlueprint,
  };
}

export function CreateSimulatorEntityForm({
  connection,
  onProblem,
  onCancel,
  onEntityCreated,
}: CreateSimulatorEntityFormProps): React.JSX.Element {
  const blueprintLabelId = useId();
  const [entityName, setEntityName] = useState('');
  const [primaryKeyField, setPrimaryKeyField] = useState('');
  const [cursorField, setCursorField] = useState<string>(
    SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD,
  );
  const [recordsPerPull, setRecordsPerPull] = useState<string>(
    String(SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL),
  );
  const [jsonContent, setJsonContent] = useState(DEFAULT_SAMPLE_JSON);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const updateMutation = useUpdateConnectionMutation(connection.id);

  const handleFormatBlueprint = (): void => {
    const outcome = parseSimulatorBlueprint(jsonContent);
    if (!outcome.ok) {
      setLocalError(outcome.reason);
      return;
    }
    setLocalError(null);
    setJsonContent(outcome.formatted);
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    setLocalError(null);
    onProblem(null);

    const cleanName = entityName.trim();
    if (!cleanName) {
      setLocalError('Please enter an entity name (e.g. orders, customers, invoices).');
      return;
    }

    const blueprintOutcome = parseSimulatorBlueprint(jsonContent);
    if (!blueprintOutcome.ok) {
      setLocalError(blueprintOutcome.reason);
      return;
    }

    const updatedPublicConfig = buildPublicConfigWithSimulatorStream(connection.publicConfig, {
      entityName: cleanName,
      sampleJson: blueprintOutcome.parsed,
      recordsPerPull: clampSimulatorRecordsPerPull(recordsPerPull),
      cursorField,
      primaryKeyField,
    });

    const res = await updateMutation.mutateAsync({
      newName: connection.name,
      updatedPublicConfig,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }

    toast.success(
      `Entity "${cleanName}" created on Simulator. Click "Discover Entities" when ready to sync.`,
    );
    onEntityCreated?.(cleanName);
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
      {localError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          {localError}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="sim-entity-name">Entity Name *</Label>
          <Input
            id="sim-entity-name"
            name="entity_name"
            value={entityName}
            onChange={(e) => {
              setLocalError(null);
              setEntityName(e.target.value);
            }}
            placeholder="e.g. orders, customers, invoices"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sim-entity-pk">Primary Key Field (optional)</Label>
          <Input
            id="sim-entity-pk"
            name="primary_key_field"
            value={primaryKeyField}
            onChange={(e) => setPrimaryKeyField(e.target.value)}
            placeholder="Auto-detected (e.g. order_id or id)"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sim-entity-cursor">Cursor Timestamp Field</Label>
          <Input
            id="sim-entity-cursor"
            name="cursor_field"
            value={cursorField}
            onChange={(e) => setCursorField(e.target.value)}
            placeholder={SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD}
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sim-entity-batch">Records Generated per Pull</Label>
          <Input
            id="sim-entity-batch"
            name="records_per_pull"
            type="number"
            min={SIMULATOR_STREAM_LIMITS.MIN_RECORDS_PER_PULL}
            max={SIMULATOR_STREAM_LIMITS.MAX_RECORDS_PER_PULL}
            value={recordsPerPull}
            onChange={(e) => setRecordsPerPull(e.target.value)}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label id={blueprintLabelId}>Entity Blueprint (JSON) *</Label>
        <MonacoCodeEditor
          ariaLabelledBy={blueprintLabelId}
          value={jsonContent}
          onChange={(nextValue) => {
            setLocalError(null);
            setJsonContent(nextValue);
          }}
          language="json"
          height={280}
          fileUpload={{
            accept: '.json,application/json',
            buttonLabel: uploadedFileName ? 'Replace .json' : 'Upload .json',
            statusText: uploadedFileName,
            toolbarVisibility: MonacoFileToolbarVisibility.ALWAYS,
            transformLoadedFile: (rawText, file) => {
              const parsedOutcome = parseSimulatorBlueprint(rawText, file.name);
              if (!parsedOutcome.ok) {
                return parsedOutcome;
              }
              return { ok: true, content: parsedOutcome.formatted };
            },
            onFileAccepted: (file) => {
              setUploadedFileName(file.name);
              setLocalError(null);
              setEntityName((prev) => {
                if (prev.trim()) {
                  return prev;
                }
                return inferSimulatorEntityNameFromFilename(file.name);
              });
            },
            extraActions: (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleFormatBlueprint}
                className="h-7 gap-1.5 px-2.5 text-xs"
              >
                <Braces className="h-3.5 w-3.5" />
                <span>Format</span>
              </Button>
            ),
          }}
        />
      </div>

      <DialogFooter className="gap-2 sm:gap-0">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={updateMutation.isPending}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={updateMutation.isPending}>
          {updateMutation.isPending ? 'Creating Entity...' : 'Create Entity'}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function CreateSimulatorEntityModal({
  open,
  onOpenChange,
  connection,
  onProblem,
  onEntityCreated,
}: CreateSimulatorEntityModalProps): React.JSX.Element {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Create Entity</DialogTitle>
        </DialogHeader>

        {open ? (
          <CreateSimulatorEntityForm
            connection={connection}
            onProblem={onProblem}
            onCancel={() => onOpenChange(false)}
            onEntityCreated={(createdName) => {
              onEntityCreated?.(createdName);
              onOpenChange(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
