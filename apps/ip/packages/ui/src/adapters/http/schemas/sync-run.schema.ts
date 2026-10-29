import { z } from 'zod';

export const SyncRunWireSchema = z.object({
  run_id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  stream_name: z.string(),
  kind: z.string(),
  generation_id: z.number(),
  status: z.string(),
  start_checkpoint: z.string().nullable().optional().default(null),
  end_checkpoint: z.string().nullable().optional().default(null),
  pages_count: z.number(),
  records_count: z.number(),
  bytes_count: z.number(),
  retry_count: z.number(),
  error_code: z.string().nullable().optional().default(null),
  error_message: z.string().nullable().optional().default(null),
  trace_id: z.string(),
  started_at: z.string().nullable().optional().default(null),
  finished_at: z.string().nullable().optional().default(null),
  created_at: z.string(),
});

export const SyncRunListWireSchema = z.array(SyncRunWireSchema);

export const StreamStateWireSchema = z.object({
  state_id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  stream_name: z.string(),
  cursor_field: z.string().nullable().optional().default(null),
  cursor_value: z.string().nullable().optional().default(null),
  records_synced_count: z.number(),
  last_synced_at: z.string(),
});

export const StreamStateListWireSchema = z.array(StreamStateWireSchema);

export type SyncRunWire = z.infer<typeof SyncRunWireSchema>;
export type StreamStateWire = z.infer<typeof StreamStateWireSchema>;
