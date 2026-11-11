import {
  type CreatedSimulatorSandbox,
  type CreateSimulatorEntityInput,
  type CreateSimulatorSandboxInput,
  SIMULATOR_STREAM_LIMITS,
  type SimulatorEntity,
  type SimulatorSandbox,
  SimulatorVelocityMode,
  type UpdateSimulatorEntityInput,
} from '../../../domain/simulator';
import type {
  CreatedSimulatorSandboxWire,
  SimulatorEntityWire,
  SimulatorSandboxWire,
} from '../schemas/simulator.schema';

export function mapSimulatorSandboxFromWire(wire: SimulatorSandboxWire): SimulatorSandbox {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    name: wire.name,
    apiKeyPrefix: wire.api_key_prefix,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export function mapCreatedSimulatorSandboxFromWire(
  wire: CreatedSimulatorSandboxWire,
): CreatedSimulatorSandbox {
  return {
    ...mapSimulatorSandboxFromWire(wire),
    apiKey: wire.api_key,
  };
}

export function mapSimulatorEntityFromWire(wire: SimulatorEntityWire): SimulatorEntity {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    sandboxId: wire.sandbox_id,
    entityName: wire.entity_name,
    primaryKeyField: wire.primary_key_field,
    cursorField: wire.cursor_field,
    recordsPerPull: wire.records_per_pull,
    cursorStepSeconds: wire.cursor_step_seconds,
    velocityMode: wire.velocity_mode,
    sampleBlueprint: wire.sample_blueprint,
    inferredJsonSchema: wire.inferred_json_schema,
    chaosPolicy: wire.chaos_policy,
    version: wire.version,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export function mapCreateSimulatorSandboxToWire(
  input: CreateSimulatorSandboxInput,
): Record<string, unknown> {
  return {
    name: input.name,
  };
}

export function mapCreateSimulatorEntityToWire(
  input: CreateSimulatorEntityInput,
): Record<string, unknown> {
  return {
    entity_name: input.entityName,
    sample_blueprint: input.sampleBlueprint,
    primary_key_field: input.primaryKeyField ?? null,
    cursor_field: input.cursorField ?? null,
    records_per_pull: input.recordsPerPull ?? SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL,
    cursor_step_seconds:
      input.cursorStepSeconds ?? SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_STEP_SECONDS,
    velocity_mode: input.velocityMode ?? SimulatorVelocityMode.ENTITY_TRANSACTIONAL,
    chaos_policy: input.chaosPolicy ?? null,
  };
}

export function mapUpdateSimulatorEntityToWire(
  input: UpdateSimulatorEntityInput,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (input.entityName !== undefined) {
    payload.entity_name = input.entityName;
  }
  if (input.sampleBlueprint !== undefined) {
    payload.sample_blueprint = input.sampleBlueprint;
  }
  if (input.primaryKeyField !== undefined) {
    payload.primary_key_field = input.primaryKeyField;
  }
  if (input.cursorField !== undefined) {
    payload.cursor_field = input.cursorField;
  }
  if (input.recordsPerPull !== undefined) {
    payload.records_per_pull = input.recordsPerPull;
  }
  if (input.cursorStepSeconds !== undefined) {
    payload.cursor_step_seconds = input.cursorStepSeconds;
  }
  if (input.velocityMode !== undefined) {
    payload.velocity_mode = input.velocityMode;
  }
  if (input.chaosPolicy !== undefined) {
    payload.chaos_policy = input.chaosPolicy;
  }
  return payload;
}
