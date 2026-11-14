import {
  type CreateSimulatorEntityInput,
  SIMULATOR_STREAM_LIMITS,
  SimulatedPushDeliveryStyle,
  type SimulatePushInput,
  type SimulatePushResult,
  type SimulatorEntity,
  SimulatorVelocityMode,
  type UpdateSimulatorEntityInput,
} from '../../../domain/simulator';
import type { SimulatePushWire, SimulatorEntityWire } from '../schemas/simulator.schema';

export function mapSimulatorEntityFromWire(wire: SimulatorEntityWire): SimulatorEntity {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    entityName: wire.entity_name,
    primaryKeyField: wire.primary_key_field,
    cursorField: wire.cursor_field,
    pushMode: wire.push_mode,
    pushConfig: wire.push_config,
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

export function mapCreateSimulatorEntityToWire(
  input: CreateSimulatorEntityInput,
): Record<string, unknown> {
  return {
    entity_name: input.entityName,
    sample_blueprint: input.sampleBlueprint,
    primary_key_field: input.primaryKeyField ?? null,
    cursor_field: input.cursorField ?? null,
    push_mode: input.pushMode ?? 'RANDOM_BURST',
    push_config: input.pushConfig ?? {},
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
  if (input.pushMode !== undefined) {
    payload.push_mode = input.pushMode;
  }
  if (input.pushConfig !== undefined) {
    payload.push_config = input.pushConfig;
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

export function mapSimulatePushToWire(input: SimulatePushInput): Record<string, unknown> {
  return {
    stream_name: input.streamName,
    count: input.count ?? 1,
    delivery_style: input.deliveryStyle ?? SimulatedPushDeliveryStyle.FULL_PAYLOAD,
    correlation_id: input.correlationId ?? null,
  };
}

export function mapSimulatePushFromWire(wire: SimulatePushWire): SimulatePushResult {
  return {
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    recordsPushed: wire.records_pushed,
    recordIds: wire.record_ids,
    traceIds: wire.trace_ids,
    status: wire.status,
  };
}
