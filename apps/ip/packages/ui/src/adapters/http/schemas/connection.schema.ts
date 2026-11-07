import { z } from 'zod';

export const ConnectionWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  app_id: z.string(),
  name: z.string(),
  auth_type: z.string(),
  public_config: z.record(z.string(), z.unknown()).default({}),
  status: z.string(),
  connection_fingerprint: z.string(),
  token_expires_at: z.string().nullable().optional().default(null),
  last_refreshed_at: z.string().nullable().optional().default(null),
  last_error_code: z.string().nullable().optional().default(null),
  last_error_message: z.string().nullable().optional().default(null),
  created_at: z.string(),
  updated_at: z.string(),
  deactivated_at: z.string().nullable().optional().default(null),
});

export const ConnectionListWireSchema = z.array(ConnectionWireSchema);

export const ConnectionCheckWireSchema = z.object({
  success: z.boolean(),
  status: z.string(),
  message: z.string().nullable().optional().default(null),
  error_code: z.string().nullable().optional().default(null),
});

export const StreamFieldWireSchema = z.object({
  name: z.string(),
  data_type: z.string(),
  nullable: z.boolean().default(true),
  description: z.string().nullable().optional().default(null),
});

export const StreamSchemaWireSchema = z.object({
  name: z.string(),
  fields: z.array(StreamFieldWireSchema).default([]),
  primary_key: z.array(z.string()).default([]),
  cursor_field: z.string().nullable().optional().default(null),
  supported_sync_modes: z.array(z.string()).default([]),
});

export const DiscoveredCatalogWireSchema = z.object({
  connection_id: z.string(),
  catalog_version: z.number(),
  catalog_hash: z.string(),
  streams: z.array(StreamSchemaWireSchema).default([]),
  discovered_at: z.string(),
});

export type ConnectionWire = z.infer<typeof ConnectionWireSchema>;
export type ConnectionCheckWire = z.infer<typeof ConnectionCheckWireSchema>;
export type DiscoveredCatalogWire = z.infer<typeof DiscoveredCatalogWireSchema>;
