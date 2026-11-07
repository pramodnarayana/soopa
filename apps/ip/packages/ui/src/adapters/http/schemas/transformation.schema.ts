import { z } from 'zod';

export const RegisteredTransformerWireSchema = z.object({
  transformation_id: z.string(),
  transformation_version: z.number(),
  target_types: z.array(z.string()).default([]),
});

export const RegisteredTransformerListWireSchema = z.array(RegisteredTransformerWireSchema);

export const TransformationWireSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  connection_id: z.string(),
  stream: z.string(),
  transformation_id: z.string(),
  transformation_version: z.number(),
  mode: z.string(),
  shadow_transformation_version: z.number().nullable().optional().default(null),
  was_created: z.boolean().nullable().optional().default(null),
});

export const TransformationListWireSchema = z.array(TransformationWireSchema);

export const PromoteTransformationWireSchema = z.object({
  id: z.string(),
  connection_id: z.string(),
  stream: z.string(),
  transformation_id: z.string(),
  promoted_version: z.number(),
  previous_version: z.number(),
});

export const PreviewReferenceWireSchema = z.object({
  field_name: z.string(),
  target_canonical_type: z.string(),
  target_source_id: z.string(),
});

export const PreviewDraftWireSchema = z.object({
  canonical_type: z.string(),
  source_id: z.string(),
  fields: z.record(z.string(), z.unknown()).default({}),
  extensions: z.record(z.string(), z.unknown()).default({}),
  references: z.array(PreviewReferenceWireSchema).default([]),
});

export const PreviewRejectionWireSchema = z.object({
  reason: z.string(),
  field_path: z.string().nullable().optional().default(null),
  detail: z.string(),
});

export const PreviewTransformationWireSchema = z.object({
  transformation_id: z.string(),
  transformation_version: z.number(),
  drafts: z.array(PreviewDraftWireSchema).default([]),
  rejections: z.array(PreviewRejectionWireSchema).default([]),
  shadow_transformation_version: z.number().nullable().optional().default(null),
  shadow_diffs: z.record(z.string(), z.record(z.string(), z.unknown())).default({}),
});

export type RegisteredTransformerWire = z.infer<typeof RegisteredTransformerWireSchema>;
export type TransformationWire = z.infer<typeof TransformationWireSchema>;
export type PromoteTransformationWire = z.infer<typeof PromoteTransformationWireSchema>;
export type PreviewTransformationWire = z.infer<typeof PreviewTransformationWireSchema>;
