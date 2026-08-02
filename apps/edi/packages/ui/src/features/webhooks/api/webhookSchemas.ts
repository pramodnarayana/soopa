import { z } from 'zod';
import type { Webhook } from '../types';

export const WebhookSchema: z.ZodType<Webhook> = z.object({
  id: z.string(),
  name: z.string(),
  url: z.string(),
  type: z.literal('WEBHOOK'),
  status: z.union([z.literal('ACTIVE'), z.literal('INACTIVE')]),
  tenant_id: z.union([z.string(), z.number()]).optional(),
});

export const WebhooksArraySchema = z.array(WebhookSchema);

export const RawWebhookResponseSchema = z.object({
  id: z.string(),
  name: z.string(),
  url: z.string(),
  active: z.boolean(),
  createdAt: z.string(),
});

export type RawWebhook = z.infer<typeof RawWebhookResponseSchema>;

export const RawWebhooksArrayResponseSchema = z.array(RawWebhookResponseSchema);
