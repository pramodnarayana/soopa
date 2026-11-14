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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui';
import { Braces, Zap } from 'lucide-react';
import React, { useId, useState } from 'react';
import { toast } from 'sonner';
import {
  useCreateSimulatorEntityMutation,
  useSimulatorEntitiesQuery,
  useUpdateSimulatorEntityMutation,
} from '../../application/use-simulator-queries';
import type { JsonRecord } from '../../domain/enums';
import {
  PushCadenceMode,
  type PushCadenceModeValue,
  SIMULATOR_STREAM_LIMITS,
  type SimulatorBlueprintJson,
  type SimulatorEntity,
  SimulatorVelocityMode,
  type SimulatorVelocityModeValue,
} from '../../domain/simulator';

export interface CreateSimulatorEntityModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly connectionId: string;
  readonly editingEntity?: SimulatorEntity | null;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onEntitySaved?: (entity: SimulatorEntity) => void;
}

export interface CreateSimulatorEntityFormProps {
  readonly connectionId: string;
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
  return `An entity named "${cleanName}" already exists in this Simulator connection. Choose a unique entity name.`;
}

export function CreateSimulatorEntityForm({
  connectionId,
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
  const [velocityMode, setVelocityMode] = useState<SimulatorVelocityModeValue>(
    editingEntity?.velocityMode ?? SimulatorVelocityMode.ENTITY_TRANSACTIONAL,
  );
  const [jsonContent, setJsonContent] = useState<string>(() =>
    editingEntity ? JSON.stringify(editingEntity.sampleBlueprint, null, 2) : DEFAULT_SAMPLE_JSON,
  );
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  // Push Cadence Options
  const [pushMode, setPushMode] = useState<PushCadenceModeValue>(
    editingEntity?.pushMode ?? PushCadenceMode.MANUAL,
  );
  const initialConfig = (editingEntity?.pushConfig ?? {}) as Record<string, unknown>;

  // Manual state:
  const [manualRecords, setManualRecords] = useState<string>(
    String(initialConfig.records_per_push ?? 1),
  );

  // Random Burst state:
  const [randomMinBatch, setRandomMinBatch] = useState<string>(
    String(initialConfig.min_batch ?? 1),
  );
  const [randomMaxBatch, setRandomMaxBatch] = useState<string>(
    String(initialConfig.max_batch ?? 10),
  );
  const [randomInterval, setRandomInterval] = useState<string>(
    String(initialConfig.interval_seconds ?? 5),
  );

  // Constant Paced state:
  const [constantRate, setConstantRate] = useState<string>(
    String(initialConfig.messages_per_second ?? 1),
  );

  // Poisson Jitter state:
  const [poissonMinDelay, setPoissonMinDelay] = useState<string>(
    String(initialConfig.min_delay_seconds ?? 1),
  );
  const [poissonMaxDelay, setPoissonMaxDelay] = useState<string>(
    String(initialConfig.max_delay_seconds ?? 10),
  );
  const [poissonMinBatch, setPoissonMinBatch] = useState<string>(
    String(initialConfig.min_batch ?? 1),
  );
  const [poissonMaxBatch, setPoissonMaxBatch] = useState<string>(
    String(initialConfig.max_batch ?? 5),
  );

  // Cron Batch state:
  const [cronBatchSize, setCronBatchSize] = useState<string>(
    String(initialConfig.batch_size ?? 500),
  );
  const [cronExpression, setCronExpression] = useState<string>(
    String(initialConfig.cron_expression ?? '*/5 * * * *'),
  );

  // Chaos Fault state:
  const [chaosDropRate, setChaosDropRate] = useState<string>(
    String(initialConfig.drop_rate_percent ?? 20),
  );
  const [chaosInterval, setChaosInterval] = useState<string>(
    String(initialConfig.base_interval_seconds ?? 1),
  );
  const [chaosBatchSize, setChaosBatchSize] = useState<string>(
    String(initialConfig.batch_size ?? 5),
  );

  // Diurnal Wave state:
  const [diurnalBaseRate, setDiurnalBaseRate] = useState<string>(
    String(initialConfig.base_rate_per_second ?? 1),
  );
  const [diurnalPeakMultiplier, setDiurnalPeakMultiplier] = useState<string>(
    String(initialConfig.peak_multiplier ?? 5),
  );
  const [diurnalPeakHour, setDiurnalPeakHour] = useState<string>(
    String(initialConfig.peak_hour_utc ?? 14),
  );

  // Thin Push state:
  const [thinInterval, setThinInterval] = useState<string>(
    String(initialConfig.interval_seconds ?? 2),
  );

  const existingEntitiesView = useSimulatorEntitiesQuery(connectionId);
  const createMutation = useCreateSimulatorEntityMutation(connectionId);
  const updateMutation = useUpdateSimulatorEntityMutation(connectionId);
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

  const validateAndBuildPushConfig = ():
    | { readonly ok: true; readonly config: Record<string, unknown> }
    | { readonly ok: false; readonly error: string } => {
    switch (pushMode) {
      case PushCadenceMode.MANUAL: {
        const count = Number.parseInt(manualRecords, 10);
        if (Number.isNaN(count) || count < 1) {
          return { ok: false, error: 'Manual: Records per push must be an integer >= 1.' };
        }
        return {
          ok: true,
          config: { records_per_push: count },
        };
      }
      case PushCadenceMode.RANDOM_BURST: {
        const minB = Number.parseInt(randomMinBatch, 10);
        const maxB = Number.parseInt(randomMaxBatch, 10);
        const intv = Number.parseFloat(randomInterval);
        if (Number.isNaN(minB) || minB < 1) {
          return { ok: false, error: 'Random Burst: Minimum batch must be an integer >= 1.' };
        }
        if (Number.isNaN(maxB) || maxB < 1) {
          return { ok: false, error: 'Random Burst: Maximum batch must be an integer >= 1.' };
        }
        if (minB > maxB) {
          return { ok: false, error: 'Random Burst: Minimum batch cannot exceed Maximum batch.' };
        }
        if (Number.isNaN(intv) || intv <= 0) {
          return { ok: false, error: 'Random Burst: Interval must be greater than 0 seconds.' };
        }
        return {
          ok: true,
          config: { min_batch: minB, max_batch: maxB, interval_seconds: intv },
        };
      }
      case PushCadenceMode.CONSTANT_PACED: {
        const rate = Number.parseFloat(constantRate);
        if (Number.isNaN(rate) || rate <= 0) {
          return {
            ok: false,
            error: 'Constant Paced: Messages per second must be greater than 0.',
          };
        }
        return {
          ok: true,
          config: { messages_per_second: rate },
        };
      }
      case PushCadenceMode.POISSON_JITTER: {
        const minD = Number.parseFloat(poissonMinDelay);
        const maxD = Number.parseFloat(poissonMaxDelay);
        const minB = Number.parseInt(poissonMinBatch, 10);
        const maxB = Number.parseInt(poissonMaxBatch, 10);
        if (Number.isNaN(minD) || minD < 0) {
          return { ok: false, error: 'Poisson Jitter: Min delay must be a non-negative number.' };
        }
        if (Number.isNaN(maxD) || maxD <= 0) {
          return { ok: false, error: 'Poisson Jitter: Max delay must be greater than 0.' };
        }
        if (minD > maxD) {
          return { ok: false, error: 'Poisson Jitter: Min delay cannot exceed Max delay.' };
        }
        if (Number.isNaN(minB) || minB < 1 || Number.isNaN(maxB) || maxB < 1) {
          return { ok: false, error: 'Poisson Jitter: Batch sizes must be integers >= 1.' };
        }
        if (minB > maxB) {
          return { ok: false, error: 'Poisson Jitter: Min batch cannot exceed Max batch.' };
        }
        return {
          ok: true,
          config: {
            min_delay_seconds: minD,
            max_delay_seconds: maxD,
            min_batch: minB,
            max_batch: maxB,
          },
        };
      }
      case PushCadenceMode.CRON_BATCH: {
        const bSize = Number.parseInt(cronBatchSize, 10);
        const cron = cronExpression.trim();
        if (Number.isNaN(bSize) || bSize < 1) {
          return { ok: false, error: 'Cron Batch: Batch size must be an integer >= 1.' };
        }
        if (cron.split(/\s+/).length !== 5) {
          return {
            ok: false,
            error:
              'Cron Batch: Cron expression must be a standard 5-part string (e.g. */5 * * * *).',
          };
        }
        return {
          ok: true,
          config: { batch_size: bSize, cron_expression: cron },
        };
      }
      case PushCadenceMode.CHAOS_FAULT: {
        const drop = Number.parseFloat(chaosDropRate);
        const intv = Number.parseFloat(chaosInterval);
        const bSize = Number.parseInt(chaosBatchSize, 10);
        if (Number.isNaN(drop) || drop < 0 || drop > 100) {
          return { ok: false, error: 'Chaos Fault: Drop rate must be between 0% and 100%.' };
        }
        if (Number.isNaN(intv) || intv <= 0) {
          return { ok: false, error: 'Chaos Fault: Base interval must be greater than 0.' };
        }
        if (Number.isNaN(bSize) || bSize < 1) {
          return { ok: false, error: 'Chaos Fault: Batch size must be an integer >= 1.' };
        }
        return {
          ok: true,
          config: {
            drop_rate_percent: drop,
            base_interval_seconds: intv,
            batch_size: bSize,
          },
        };
      }
      case PushCadenceMode.DIURNAL_WAVE: {
        const baseRate = Number.parseFloat(diurnalBaseRate);
        const peakMult = Number.parseFloat(diurnalPeakMultiplier);
        const peakHour = Number.parseInt(diurnalPeakHour, 10);
        if (Number.isNaN(baseRate) || baseRate <= 0) {
          return { ok: false, error: 'Diurnal Wave: Base rate must be greater than 0.' };
        }
        if (Number.isNaN(peakMult) || peakMult < 1) {
          return { ok: false, error: 'Diurnal Wave: Peak multiplier must be >= 1.0.' };
        }
        if (Number.isNaN(peakHour) || peakHour < 0 || peakHour > 23) {
          return { ok: false, error: 'Diurnal Wave: Peak hour must be between 0 and 23.' };
        }
        return {
          ok: true,
          config: {
            base_rate_per_second: baseRate,
            peak_multiplier: peakMult,
            peak_hour_utc: peakHour,
          },
        };
      }
      case PushCadenceMode.THIN_PUSH: {
        const intv = Number.parseFloat(thinInterval);
        if (Number.isNaN(intv) || intv <= 0) {
          return { ok: false, error: 'Thin Push: Ping interval must be greater than 0.' };
        }
        return {
          ok: true,
          config: { interval_seconds: intv },
        };
      }
      default:
        return { ok: true, config: {} };
    }
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

    const pushOutcome = validateAndBuildPushConfig();
    if (!pushOutcome.ok) {
      setLocalError(pushOutcome.error);
      return;
    }

    const normalizedPrimaryKey = primaryKeyField.trim() || null;
    const existingCursor = editingEntity?.cursorField ?? null;

    const res = editingEntity
      ? await updateMutation.mutateAsync({
          entityId: editingEntity.id,
          input: {
            entityName: cleanName,
            sampleBlueprint: blueprintOutcome.parsed,
            primaryKeyField: normalizedPrimaryKey,
            cursorField: existingCursor,
            pushMode,
            pushConfig: pushOutcome.config,
            velocityMode,
          },
        })
      : await createMutation.mutateAsync({
          entityName: cleanName,
          sampleBlueprint: blueprintOutcome.parsed,
          primaryKeyField: normalizedPrimaryKey,
          cursorField: null,
          pushMode,
          pushConfig: pushOutcome.config,
          velocityMode,
        });

    if (!res.ok) {
      onProblem(res.error);
      return;
    }

    toast.success(
      isEditing
        ? `Entity "${res.value.entityName}" updated in this Simulator connection (v${res.value.version}).`
        : `Entity "${res.value.entityName}" created in this Simulator connection.`,
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
            placeholder="orders"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sim-entity-pk">Primary Key</Label>
          <Input
            id="sim-entity-pk"
            name="primary_key_field"
            value={primaryKeyField}
            onChange={(e) => {
              setLocalError(null);
              setPrimaryKeyField(e.target.value);
            }}
            placeholder="Auto-detected (e.g. id, order_id)"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </div>
      </div>

      {/* Push Emission Cadence Configuration */}
      <fieldset className="space-y-3 rounded-lg border border-border bg-card p-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Zap className="h-4 w-4 text-primary" />
            <legend className="text-xs font-semibold uppercase tracking-wider text-foreground">
              Push Delivery Options
            </legend>
          </div>
          <span className="text-[11px] text-muted-foreground">
            Configure how simulated webhook events are emitted
          </span>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sim-push-mode" className="text-xs text-muted-foreground">
            Push Emission Mode
          </Label>
          <Select
            value={pushMode}
            onValueChange={(val) => {
              setLocalError(null);
              setPushMode(val as PushCadenceModeValue);
            }}
          >
            <SelectTrigger
              id="sim-push-mode"
              aria-label="Select Push Mode"
              className="h-8 text-xs font-medium"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={PushCadenceMode.MANUAL}>
                Manual (On-Demand trigger per click)
              </SelectItem>
              <SelectItem value={PushCadenceMode.RANDOM_BURST}>
                Random Burst (Random burst size & variable interval)
              </SelectItem>
              <SelectItem value={PushCadenceMode.CONSTANT_PACED}>
                Constant Paced (Fixed rate, e.g. 1 message every sec)
              </SelectItem>
              <SelectItem value={PushCadenceMode.POISSON_JITTER}>
                Poisson Jitter (Stochastic delays & variable batch sizes)
              </SelectItem>
              <SelectItem value={PushCadenceMode.CRON_BATCH}>
                Scheduled Cron Batch (Periodic bulk emission)
              </SelectItem>
              <SelectItem value={PushCadenceMode.CHAOS_FAULT}>
                Chaos & Fault Injection (Deliberate packet drops & latency)
              </SelectItem>
              <SelectItem value={PushCadenceMode.DIURNAL_WAVE}>
                Diurnal Wave (Circadian day/night curve with peak hours)
              </SelectItem>
              <SelectItem value={PushCadenceMode.THIN_PUSH}>
                Thin Push (Lightweight ping notifications)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Dynamic Mode-Specific Inputs */}
        {pushMode === PushCadenceMode.MANUAL ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-manual-records" className="text-xs">
                Records per Push
              </Label>
              <Input
                id="sim-manual-records"
                type="number"
                min={1}
                max={5000}
                value={manualRecords}
                onChange={(e) => {
                  setLocalError(null);
                  setManualRecords(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">
                Number of records emitted when "Simulate Data" is clicked
              </p>
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.RANDOM_BURST ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-burst-min" className="text-xs">
                Min Burst Batch
              </Label>
              <Input
                id="sim-burst-min"
                type="number"
                min={1}
                max={5000}
                value={randomMinBatch}
                onChange={(e) => {
                  setLocalError(null);
                  setRandomMinBatch(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">e.g. 2 at a time</p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-burst-max" className="text-xs">
                Max Burst Batch
              </Label>
              <Input
                id="sim-burst-max"
                type="number"
                min={1}
                max={5000}
                value={randomMaxBatch}
                onChange={(e) => {
                  setLocalError(null);
                  setRandomMaxBatch(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">e.g. 6 at a time</p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-burst-interval" className="text-xs">
                Interval (Seconds)
              </Label>
              <Input
                id="sim-burst-interval"
                type="number"
                step="0.1"
                min={0.01}
                value={randomInterval}
                onChange={(e) => {
                  setLocalError(null);
                  setRandomInterval(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">Seconds between bursts</p>
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.CONSTANT_PACED ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-paced-rate" className="text-xs">
                Messages per Second
              </Label>
              <Input
                id="sim-paced-rate"
                type="number"
                step="0.1"
                min={0.001}
                value={constantRate}
                onChange={(e) => {
                  setLocalError(null);
                  setConstantRate(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">
                e.g. 1.0 = 1 msg every sec, 0.2 = 1 msg every 5 sec
              </p>
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.POISSON_JITTER ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-poisson-mindelay" className="text-xs">
                Min Delay (s)
              </Label>
              <Input
                id="sim-poisson-mindelay"
                type="number"
                step="0.1"
                min={0}
                value={poissonMinDelay}
                onChange={(e) => {
                  setLocalError(null);
                  setPoissonMinDelay(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-poisson-maxdelay" className="text-xs">
                Max Delay (s)
              </Label>
              <Input
                id="sim-poisson-maxdelay"
                type="number"
                step="0.1"
                min={0.1}
                value={poissonMaxDelay}
                onChange={(e) => {
                  setLocalError(null);
                  setPoissonMaxDelay(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-poisson-minbatch" className="text-xs">
                Min Batch
              </Label>
              <Input
                id="sim-poisson-minbatch"
                type="number"
                min={1}
                value={poissonMinBatch}
                onChange={(e) => {
                  setLocalError(null);
                  setPoissonMinBatch(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-poisson-maxbatch" className="text-xs">
                Max Batch
              </Label>
              <Input
                id="sim-poisson-maxbatch"
                type="number"
                min={1}
                value={poissonMaxBatch}
                onChange={(e) => {
                  setLocalError(null);
                  setPoissonMaxBatch(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.CRON_BATCH ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-cron-batch" className="text-xs">
                Batch Size
              </Label>
              <Input
                id="sim-cron-batch"
                type="number"
                min={1}
                value={cronBatchSize}
                onChange={(e) => {
                  setLocalError(null);
                  setCronBatchSize(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">Records emitted per cron cycle</p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-cron-expr" className="text-xs">
                Cron Expression
              </Label>
              <Input
                id="sim-cron-expr"
                value={cronExpression}
                onChange={(e) => {
                  setLocalError(null);
                  setCronExpression(e.target.value);
                }}
                placeholder="*/5 * * * *"
                className="h-8 font-mono text-xs"
              />
              <p className="text-[10px] text-muted-foreground">
                5-part cron syntax (e.g. */5 * * * *)
              </p>
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.CHAOS_FAULT ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-chaos-drop" className="text-xs">
                Drop Rate (%)
              </Label>
              <Input
                id="sim-chaos-drop"
                type="number"
                min={0}
                max={100}
                step="1"
                value={chaosDropRate}
                onChange={(e) => {
                  setLocalError(null);
                  setChaosDropRate(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">Percentage of dropped packets</p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-chaos-interval" className="text-xs">
                Base Interval (s)
              </Label>
              <Input
                id="sim-chaos-interval"
                type="number"
                step="0.1"
                min={0.01}
                value={chaosInterval}
                onChange={(e) => {
                  setLocalError(null);
                  setChaosInterval(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-chaos-batch" className="text-xs">
                Batch Size
              </Label>
              <Input
                id="sim-chaos-batch"
                type="number"
                min={1}
                value={chaosBatchSize}
                onChange={(e) => {
                  setLocalError(null);
                  setChaosBatchSize(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.DIURNAL_WAVE ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-diurnal-base" className="text-xs">
                Base Rate (msg/s)
              </Label>
              <Input
                id="sim-diurnal-base"
                type="number"
                step="0.1"
                min={0.01}
                value={diurnalBaseRate}
                onChange={(e) => {
                  setLocalError(null);
                  setDiurnalBaseRate(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-diurnal-mult" className="text-xs">
                Peak Multiplier
              </Label>
              <Input
                id="sim-diurnal-mult"
                type="number"
                step="0.5"
                min={1}
                value={diurnalPeakMultiplier}
                onChange={(e) => {
                  setLocalError(null);
                  setDiurnalPeakMultiplier(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-diurnal-hour" className="text-xs">
                Peak Hour (UTC)
              </Label>
              <Input
                id="sim-diurnal-hour"
                type="number"
                min={0}
                max={23}
                value={diurnalPeakHour}
                onChange={(e) => {
                  setLocalError(null);
                  setDiurnalPeakHour(e.target.value);
                }}
                className="h-8 text-xs"
              />
            </div>
          </div>
        ) : null}

        {pushMode === PushCadenceMode.THIN_PUSH ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="sim-thin-interval" className="text-xs">
                Ping Interval (Seconds)
              </Label>
              <Input
                id="sim-thin-interval"
                type="number"
                step="0.1"
                min={0.01}
                value={thinInterval}
                onChange={(e) => {
                  setLocalError(null);
                  setThinInterval(e.target.value);
                }}
                className="h-8 text-xs"
              />
              <p className="text-[10px] text-muted-foreground">
                Seconds between lightweight ping events
              </p>
            </div>
          </div>
        ) : null}
      </fieldset>

      <fieldset className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
        <legend className="px-1 text-xs font-medium text-foreground">Stream Velocity Mode</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-card p-2.5 text-xs">
            <input
              type="radio"
              name="velocity_mode"
              value={SimulatorVelocityMode.ENTITY_TRANSACTIONAL}
              checked={velocityMode === SimulatorVelocityMode.ENTITY_TRANSACTIONAL}
              onChange={() => setVelocityMode(SimulatorVelocityMode.ENTITY_TRANSACTIONAL)}
              className="accent-primary"
            />
            <span className="font-semibold text-foreground">Transactional Entity</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-card p-2.5 text-xs">
            <input
              type="radio"
              name="velocity_mode"
              value={SimulatorVelocityMode.TIMESERIES_COLUMNAR}
              checked={velocityMode === SimulatorVelocityMode.TIMESERIES_COLUMNAR}
              onChange={() => setVelocityMode(SimulatorVelocityMode.TIMESERIES_COLUMNAR)}
              className="accent-primary"
            />
            <span className="font-semibold text-foreground">Time-Series Columnar</span>
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
  connectionId,
  editingEntity,
  onProblem,
  onEntitySaved,
}: CreateSimulatorEntityModalProps): React.JSX.Element {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby={undefined}
        className="sm:max-w-2xl max-h-[90vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{editingEntity ? 'Edit Entity' : 'Create Entity'}</DialogTitle>
        </DialogHeader>

        {open ? (
          <CreateSimulatorEntityForm
            key={editingEntity?.id ?? 'new'}
            connectionId={connectionId}
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
