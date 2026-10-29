import { z } from 'zod';

export const DropdownOptionWireSchema = z.object({
  label: z.string(),
  value: z.string(),
});

export const OAuthConfigWireSchema = z.object({
  auth_url: z.string(),
  token_url: z.string(),
  scopes: z.array(z.string()).default([]),
  client_id: z.string().nullable().optional().default(null),
});

export const ConnectorPropertyWireSchema = z.object({
  name: z.string(),
  label: z.string(),
  type: z.string(),
  required: z.boolean().default(true),
  default: z.union([z.string(), z.number(), z.boolean()]).nullable().optional().default(null),
  description: z.string().nullable().optional().default(null),
  options: z.array(DropdownOptionWireSchema).default([]),
  oauth_config: OAuthConfigWireSchema.nullable().optional().default(null),
});

export const CatalogAppSummaryWireSchema = z.object({
  app_id: z.string(),
  display_name: z.string(),
  category: z.string(),
  auth_type: z.string(),
  description: z.string().nullable().optional().default(null),
  connector_type: z.string().default('DECLARATIVE_HTTP'),
  icon_url: z.string().nullable().optional().default(null),
});

export const CatalogAppSummaryListWireSchema = z.array(CatalogAppSummaryWireSchema);

export const AppSpecWireSchema = z.object({
  app_id: z.string(),
  display_name: z.string(),
  auth_type: z.string(),
  category: z.string(),
  properties: z.array(ConnectorPropertyWireSchema).default([]),
  description: z.string().nullable().optional().default(null),
});

export type CatalogAppSummaryWire = z.infer<typeof CatalogAppSummaryWireSchema>;
export type ConnectorPropertyWire = z.infer<typeof ConnectorPropertyWireSchema>;
export type AppSpecWire = z.infer<typeof AppSpecWireSchema>;
