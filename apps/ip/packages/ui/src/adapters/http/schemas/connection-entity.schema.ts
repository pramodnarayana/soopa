import { z } from 'zod';

export const ConnectionEntityFieldWireSchema = z.object({
  name: z.string(),
  data_type: z.string(),
  nullable: z.boolean().default(true),
  description: z.string().nullable().optional().default(null),
});

export const ConnectionEntityWireSchema = z.object({
  entity_id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  stream_name: z.string(),
  sync_mode: z.string(),
  schedule: z.string(),
  sync_from: z.string(),
  sync_from_at: z.string().nullable().optional().default(null),
  is_enabled: z.boolean().default(true),
  primary_key: z.array(z.string()).default([]),
  fields: z.array(ConnectionEntityFieldWireSchema).default([]),
  cursor_field: z.string().nullable().optional().default(null),
  cursor_value: z.string().nullable().optional().default(null),
  records_synced_count: z.number().default(0),
  last_synced_at: z.string().nullable().optional().default(null),
  created_at: z.string(),
  updated_at: z.string(),
});

export const ConnectionEntityListWireSchema = z.array(ConnectionEntityWireSchema);

export type ConnectionEntityFieldWire = z.infer<typeof ConnectionEntityFieldWireSchema>;
export type ConnectionEntityWire = z.infer<typeof ConnectionEntityWireSchema>;
