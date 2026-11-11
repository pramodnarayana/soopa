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
import {
  useCreateSimulatorEntityMutation,
  useSimulatorEntitiesQuery,
  useUpdateSimulatorEntityMutation,
} from '../../application/use-simulator-queries';
import type { JsonRecord } from '../../domain/enums';
import {
  clampSimulatorRecordsPerPull,
  SIMULATOR_STREAM_LIMITS,
  type SimulatorBlueprintJson,
  type SimulatorEntity,
  SimulatorVelocityMode,
  type SimulatorVelocityModeValue,
} from '../../domain/simulator';

export interface CreateSimulatorEntityModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly sandboxId: string;
  readonly editingEntity?: SimulatorEntity | null;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onEntitySaved?: (entity: SimulatorEntity) => void;
}

export interface CreateSimulatorEntityFormProps {
  readonly sandboxId: string;
  readonly editingEntity?: SimulatorEntity | null;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onCancel: () => void;
  readonly onEntitySaved?: (entity: SimulatorEntity) => void;
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

function isJsonRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isReadonlyUnknownArray(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
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

  let normalizedBlueprint: SimulatorBlueprintJson;
  if (isReadonlyUnknownArray(parsed)) {
    normalizedBlueprint = parsed;
  } else if (isJsonRecord(parsed)) {
    normalizedBlueprint = parsed;
  } else {
    return {
      ok: false,
      reason: 'JSON blueprint must be a JSON object or array of sample objects.',
    };
  }

  return {
    ok: true,
    formatted: JSON.stringify(normalizedBlueprint, null, 2),
    parsed: normalizedBlueprint,
  };
}

export function findDuplicateSimulatorEntityError(
  existingEntities: readonly { readonly id: string; readonly entityName: string }[],
  candidateName: string,
  editingEntityId?: string,
): string | null {
  const cleanName = candidateName.trim();
  if (!cleanName) {
    return null;
  }
  const hasDuplicate = existingEntities.some(
    (existing) =>
      existing.id !== editingEntityId &&
      existing.entityName.toLowerCase() === cleanName.toLowerCase(),
  );
  if (!hasDuplicate) {
    return null;
  }
  return `An entity named "${cleanName}" already exists in this Virtual Sandbox. Choose a unique entity name.`;
}

export function CreateSimulatorEntityForm({
  sandboxId,
  editingEntity,
  onProblem,
  onCancel,
  onEntitySaved,
}: CreateSimulatorEntityFormProps): React.JSX.Element {
  const blueprintLabelId = useId();
  const isEditing = Boolean(editingEntity);
  const [entityName, setEntityName] = useState<string>(editingEntity?.entityName ?? '');
  const [primaryKeyField, setPrimaryKeyField] = useState<string>(
    editingEntity?.primaryKeyField ?? '',
  );
  const [cursorField, setCursorField] = useState<string>(
    editingEntity?.cursorField ?? SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD,
  );
  const [recordsPerPull, setRecordsPerPull] = useState<string>(
    String(editingEntity?.recordsPerPull ?? SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL),
  );
  const [velocityMode, setVelocityMode] = useState<SimulatorVelocityModeValue>(
    editingEntity?.velocityMode ?? SimulatorVelocityMode.ENTITY_TRANSACTIONAL,
  );
  const [jsonContent, setJsonContent] = useState<string>(() =>
    editingEntity ? JSON.stringify(editingEntity.sampleBlueprint, null, 2) : DEFAULT_SAMPLE_JSON,
  );
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const existingEntitiesView = useSimulatorEntitiesQuery(sandboxId);
  const createMutation = useCreateSimulatorEntityMutation(sandboxId);
  const updateMutation = useUpdateSimulatorEntityMutation(sandboxId);
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

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

    const duplicateError = findDuplicateSimulatorEntityError(
      existingEntitiesView.data ?? [],
      cleanName,
      editingEntity?.id,
    );
    if (duplicateError) {
      setLocalError(duplicateError);
      return;
    }

    const blueprintOutcome = parseSimulatorBlueprint(jsonContent);
    if (!blueprintOutcome.ok) {
      setLocalError(blueprintOutcome.reason);
      return;
    }

    const normalizedBatchSize = clampSimulatorRecordsPerPull(recordsPerPull);
    const normalizedPrimaryKey = primaryKeyField.trim() || null;
    const normalizedCursor = cursorField.trim() || SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD;

    const res = editingEntity
      ? await updateMutation.mutateAsync({
          entityId: editingEntity.id,
          input: {
            entityName: cleanName,
            sampleBlueprint: blueprintOutcome.parsed,
            primaryKeyField: normalizedPrimaryKey,
            cursorField: normalizedCursor,
            recordsPerPull: normalizedBatchSize,
            velocityMode,
          },
        })
      : await createMutation.mutateAsync({
          entityName: cleanName,
          sampleBlueprint: blueprintOutcome.parsed,
          primaryKeyField: normalizedPrimaryKey,
          cursorField: normalizedCursor,
          recordsPerPull: normalizedBatchSize,
          velocityMode,
        });

    if (!res.ok) {
      onProblem(res.error);
      return;
    }

    toast.success(
      isEditing
        ? `Entity "${res.value.entityName}" updated in Virtual Sandbox (v${res.value.version}).`
        : `Entity "${res.value.entityName}" created in Virtual Sandbox. Run "Discover Entities" when ready to sync.`,
    );
    onEntitySaved?.(res.value);
  };

  return (
    <form method="post" onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
      {localError ? (
        <div
          role="alert"
          aria-live="polite"
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
            onChange={(e) => {
              setLocalError(null);
              setPrimaryKeyField(e.target.value);
            }}
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
            onChange={(e) => {
              setLocalError(null);
              setCursorField(e.target.value);
            }}
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
            onChange={(e) => {
              setLocalError(null);
              setRecordsPerPull(e.target.value);
            }}
          />
        </div>
      </div>

      <fieldset className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
        <legend className="px-1 text-xs font-medium text-foreground">Stream Velocity Mode</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border bg-card p-2.5 text-xs">
            <input
              type="radio"
              name="velocity_mode"
              value={SimulatorVelocityMode.ENTITY_TRANSACTIONAL}
              checked={velocityMode === SimulatorVelocityMode.ENTITY_TRANSACTIONAL}
              onChange={() => setVelocityMode(SimulatorVelocityMode.ENTITY_TRANSACTIONAL)}
              className="mt-0.5 accent-primary"
            />
            <span>
              <span className="block font-semibold text-foreground">Transactional Entity</span>
              <span className="text-muted-foreground">Gear 1 OLTP records (orders, invoices)</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border bg-card p-2.5 text-xs">
            <input
              type="radio"
              name="velocity_mode"
              value={SimulatorVelocityMode.TIMESERIES_COLUMNAR}
              checked={velocityMode === SimulatorVelocityMode.TIMESERIES_COLUMNAR}
              onChange={() => setVelocityMode(SimulatorVelocityMode.TIMESERIES_COLUMNAR)}
              className="mt-0.5 accent-primary"
            />
            <span>
              <span className="block font-semibold text-foreground">Time-Series Columnar</span>
              <span className="text-muted-foreground">
                Gear 2 columnar batches (telemetry, logs)
              </span>
            </span>
          </label>
        </div>
      </fieldset>

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
          height={260}
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
          disabled={isSubmitting}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={isSubmitting}>
          {isSubmitting
            ? isEditing
              ? 'Saving Entity...'
              : 'Creating Entity...'
            : isEditing
              ? 'Save Entity'
              : 'Create Entity'}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function CreateSimulatorEntityModal({
  open,
  onOpenChange,
  sandboxId,
  editingEntity,
  onProblem,
  onEntitySaved,
}: CreateSimulatorEntityModalProps): React.JSX.Element {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editingEntity ? 'Edit Entity' : 'Create Entity'}</DialogTitle>
        </DialogHeader>

        {open ? (
          <CreateSimulatorEntityForm
            key={editingEntity?.id ?? 'new'}
            sandboxId={sandboxId}
            editingEntity={editingEntity}
            onProblem={onProblem}
            onCancel={() => onOpenChange(false)}
            onEntitySaved={(saved) => {
              onEntitySaved?.(saved);
              onOpenChange(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
