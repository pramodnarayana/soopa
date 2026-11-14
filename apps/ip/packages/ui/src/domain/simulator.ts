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

export const PushCadenceMode = {
  MANUAL: 'MANUAL',
  RANDOM_BURST: 'RANDOM_BURST',
  CONSTANT_PACED: 'CONSTANT_PACED',
  POISSON_JITTER: 'POISSON_JITTER',
  CRON_BATCH: 'CRON_BATCH',
  CHAOS_FAULT: 'CHAOS_FAULT',
  DIURNAL_WAVE: 'DIURNAL_WAVE',
  THIN_PUSH: 'THIN_PUSH',
} as const;

export type PushCadenceModeValue = (typeof PushCadenceMode)[keyof typeof PushCadenceMode];

export type SimulatorBlueprintJson = JsonRecord | readonly unknown[];

export interface SimulatorEntity {
  readonly id: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly entityName: string;
  readonly primaryKeyField: string;
  readonly cursorField: string;
  readonly pushMode: PushCadenceModeValue;
  readonly pushConfig: JsonRecord;
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

export interface CreateSimulatorEntityInput {
  readonly entityName: string;
  readonly sampleBlueprint: SimulatorBlueprintJson;
  readonly primaryKeyField?: string | null;
  readonly cursorField?: string | null;
  readonly pushMode?: PushCadenceModeValue;
  readonly pushConfig?: JsonRecord;
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
  readonly pushMode?: PushCadenceModeValue | null;
  readonly pushConfig?: JsonRecord | null;
  readonly recordsPerPull?: number | null;
  readonly cursorStepSeconds?: number | null;
  readonly velocityMode?: SimulatorVelocityModeValue | null;
  readonly chaosPolicy?: JsonRecord | null;
}

export const SimulatedPushDeliveryStyle = {
  FULL_PAYLOAD: 'FULL_PAYLOAD',
  THIN_PING: 'THIN_PING',
} as const;

export type SimulatedPushDeliveryStyleValue =
  (typeof SimulatedPushDeliveryStyle)[keyof typeof SimulatedPushDeliveryStyle];

export interface SimulatePushInput {
  readonly streamName: string;
  readonly count?: number;
  readonly deliveryStyle?: SimulatedPushDeliveryStyleValue;
  readonly correlationId?: string | null;
}

export interface SimulatePushResult {
  readonly connectionId: string;
  readonly streamName: string;
  readonly recordsPushed: number;
  readonly recordIds: readonly string[];
  readonly traceIds: readonly string[];
  readonly status: string;
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
