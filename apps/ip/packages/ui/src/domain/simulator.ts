import type { JsonRecord } from './enums';

export const SIMULATOR_STREAM_LIMITS = {
  MIN_RECORDS_PER_PULL: 1,
  MAX_RECORDS_PER_PULL: 5_000,
  DEFAULT_RECORDS_PER_PULL: 25,
  DEFAULT_CURSOR_STEP_SECONDS: 60,
  DEFAULT_CURSOR_FIELD: 'updated_at',
} as const;

export const SimulatorVelocityMode = {
  ENTITY_TRANSACTIONAL: 'ENTITY_TRANSACTIONAL',
  TIMESERIES_COLUMNAR: 'TIMESERIES_COLUMNAR',
} as const;

export type SimulatorVelocityModeValue =
  (typeof SimulatorVelocityMode)[keyof typeof SimulatorVelocityMode];

export const SIMULATOR_CONFIG_KEYS = {
  SANDBOX_ID: 'sandbox_id',
  API_KEY: 'api_key',
} as const;

export type SimulatorBlueprintJson = JsonRecord | readonly unknown[];

export interface SimulatorSandbox {
  readonly id: string;
  readonly tenantId: string;
  readonly name: string;
  readonly apiKeyPrefix: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface CreatedSimulatorSandbox extends SimulatorSandbox {
  readonly apiKey: string;
}

export interface SimulatorEntity {
  readonly id: string;
  readonly tenantId: string;
  readonly sandboxId: string;
  readonly entityName: string;
  readonly primaryKeyField: string;
  readonly cursorField: string;
  readonly recordsPerPull: number;
  readonly cursorStepSeconds: number;
  readonly velocityMode: SimulatorVelocityModeValue;
  readonly sampleBlueprint: SimulatorBlueprintJson;
  readonly inferredJsonSchema: JsonRecord;
  readonly chaosPolicy: JsonRecord;
  readonly version: number;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface CreateSimulatorSandboxInput {
  readonly name: string;
}

export interface CreateSimulatorEntityInput {
  readonly entityName: string;
  readonly sampleBlueprint: SimulatorBlueprintJson;
  readonly primaryKeyField?: string | null;
  readonly cursorField?: string | null;
  readonly recordsPerPull?: number;
  readonly cursorStepSeconds?: number;
  readonly velocityMode?: SimulatorVelocityModeValue;
  readonly chaosPolicy?: JsonRecord | null;
}

export interface UpdateSimulatorEntityInput {
  readonly entityName?: string | null;
  readonly sampleBlueprint?: SimulatorBlueprintJson | null;
  readonly primaryKeyField?: string | null;
  readonly cursorField?: string | null;
  readonly recordsPerPull?: number | null;
  readonly cursorStepSeconds?: number | null;
  readonly velocityMode?: SimulatorVelocityModeValue | null;
  readonly chaosPolicy?: JsonRecord | null;
}

export function clampSimulatorRecordsPerPull(rawInput: string | number): number {
  const parsed =
    typeof rawInput === 'number' ? Math.trunc(rawInput) : Number.parseInt(rawInput, 10);
  if (!Number.isFinite(parsed)) {
    return SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL;
  }
  return Math.max(
    SIMULATOR_STREAM_LIMITS.MIN_RECORDS_PER_PULL,
    Math.min(SIMULATOR_STREAM_LIMITS.MAX_RECORDS_PER_PULL, parsed),
  );
}

export function extractSimulatorSandboxId(
  publicConfig: JsonRecord | null | undefined,
): string | null {
  if (!publicConfig) {
    return null;
  }
  const raw = publicConfig[SIMULATOR_CONFIG_KEYS.SANDBOX_ID];
  if (typeof raw !== 'string') {
    return null;
  }
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}
