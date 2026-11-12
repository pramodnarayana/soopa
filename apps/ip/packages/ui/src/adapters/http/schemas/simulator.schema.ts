import { z } from 'zod';
import { SimulatorVelocityMode } from '../../../domain/simulator';

export const SimulatorBlueprintWireSchema = z.union([
  z.record(z.string(), z.unknown()),
  z.array(z.unknown()),
]);

export const SimulatorEntityWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  entity_name: z.string(),
  primary_key_field: z.string(),
  cursor_field: z.string(),
  records_per_pull: z.number(),
  cursor_step_seconds: z.number().default(60),
  velocity_mode: z
    .enum([SimulatorVelocityMode.ENTITY_TRANSACTIONAL, SimulatorVelocityMode.TIMESERIES_COLUMNAR])
    .default(SimulatorVelocityMode.ENTITY_TRANSACTIONAL),
  sample_blueprint: SimulatorBlueprintWireSchema,
  inferred_json_schema: z.record(z.string(), z.unknown()).default({}),
  chaos_policy: z.record(z.string(), z.unknown()).default({}),
  version: z.number().default(1),
  created_at: z.string(),
  updated_at: z.string(),
});

export const SimulatorEntityListWireSchema = z.array(SimulatorEntityWireSchema);

export const SimulatePushWireSchema = z.object({
  connection_id: z.string(),
  stream_name: z.string(),
  records_pushed: z.number(),
  record_ids: z.array(z.string()).default([]),
  trace_ids: z.array(z.string()).default([]),
  status: z.string().default('ACCEPTED'),
});

export type SimulatorEntityWire = z.infer<typeof SimulatorEntityWireSchema>;
export type SimulatePushWire = z.infer<typeof SimulatePushWireSchema>;
