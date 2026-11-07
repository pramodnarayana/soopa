import { z } from 'zod';

export const StitchNodeWireSchema = z.object({
  node_key: z.string(),
  kind: z.string(),
  step_type: z.string(),
  parents: z.array(z.string()).default([]),
  edge_condition: z.string(),
  effect_policy: z.string(),
  wait_event_key: z.string().nullable().optional().default(null),
  queue_name: z.string(),
});

export const StitchDefinitionWireSchema = z.object({
  workflow_id: z.string(),
  version: z.number(),
  default_priority: z.string(),
  description: z.string(),
  nodes: z.array(StitchNodeWireSchema).default([]),
});

export const StitchDefinitionListWireSchema = z.array(StitchDefinitionWireSchema);

export const StitchWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  workflow_id: z.string(),
  workflow_version: z.number(),
  canonical_event_type: z.string(),
  is_trigger: z.boolean(),
  condition_event_key: z.string().nullable().optional().default(null),
  idempotency_key_field: z.string(),
  concurrency_key_field: z.string().nullable().optional().default(null),
  resource_hint_field: z.string().nullable().optional().default(null),
  is_active: z.boolean(),
});

export const StitchListWireSchema = z.array(StitchWireSchema);

export const TriggerStitchEventWireSchema = z.object({
  started_run_ids: z.array(z.string()).default([]),
  deduplicated_run_ids: z.array(z.string()).default([]),
  signalled_step_ids: z.array(z.string()).default([]),
});

export const StitchStepRunWireSchema = z.object({
  step_run_id: z.string(),
  node_key: z.string(),
  status: z.string(),
  retry_count: z.number(),
  app_retry_count: z.number(),
  internal_retry_count: z.number(),
  iteration_count: z.number(),
  failure_code: z.string().nullable().optional().default(null),
  failure_detail: z.string().nullable().optional().default(null),
  created_at: z.string(),
  finished_at: z.string().nullable().optional().default(null),
});

export const StitchRunWireSchema = z.object({
  run_id: z.string(),
  tenant_id: z.string(),
  workflow_id: z.string(),
  workflow_version: z.number(),
  status: z.string(),
  priority: z.string(),
  concurrency_key: z.string().nullable().optional().default(null),
  idempotency_key: z.string(),
  trace_id: z.string(),
  correlation_id: z.string().nullable().optional().default(null),
  failure_code: z.string().nullable().optional().default(null),
  failure_detail: z.string().nullable().optional().default(null),
  created_at: z.string(),
  started_at: z.string().nullable().optional().default(null),
  finished_at: z.string().nullable().optional().default(null),
  steps: z.array(StitchStepRunWireSchema).default([]),
});

export const StitchRunListWireSchema = z.array(StitchRunWireSchema);

export type StitchDefinitionWire = z.infer<typeof StitchDefinitionWireSchema>;
export type StitchWire = z.infer<typeof StitchWireSchema>;
export type TriggerStitchEventWire = z.infer<typeof TriggerStitchEventWireSchema>;
export type StitchRunWire = z.infer<typeof StitchRunWireSchema>;
