import { z } from 'zod';
import { SimulatorVelocityMode } from '../../../domain/simulator';

export const SimulatorSandboxWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  api_key_prefix: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const SimulatorSandboxListWireSchema = z.array(SimulatorSandboxWireSchema);

export const CreatedSimulatorSandboxWireSchema = SimulatorSandboxWireSchema.extend({
  api_key: z.string(),
});

export const SimulatorBlueprintWireSchema = z.union([
  z.record(z.string(), z.unknown()),
  z.array(z.unknown()),
]);

export const SimulatorEntityWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  sandbox_id: z.string(),
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

export type SimulatorSandboxWire = z.infer<typeof SimulatorSandboxWireSchema>;
export type CreatedSimulatorSandboxWire = z.infer<typeof CreatedSimulatorSandboxWireSchema>;
export type SimulatorEntityWire = z.infer<typeof SimulatorEntityWireSchema>;
