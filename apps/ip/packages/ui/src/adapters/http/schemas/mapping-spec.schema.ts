import { z } from 'zod';

export const MappingRuleWireSchema = z.object({
  target_field: z.string(),
  rule_type: z.string().default('DIRECT'),
  source_field: z.string().nullable().optional().default(null),
  constant_value: z.union([z.string(), z.number(), z.boolean(), z.null()]).optional().default(null),
  expression: z.string().nullable().optional().default(null),
});

export const MappingSpecWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  description: z.string().optional().default(''),
  source_type: z.string(),
  target_connection_id: z.string(),
  target_entity_name: z.string(),
  version: z.number().default(1),
  rules: z.array(MappingRuleWireSchema).default([]),
  is_active: z.boolean().default(true),
});

export const MappingSpecListWireSchema = z.array(MappingSpecWireSchema);

export type MappingRuleWire = z.infer<typeof MappingRuleWireSchema>;
export type MappingSpecWire = z.infer<typeof MappingSpecWireSchema>;
