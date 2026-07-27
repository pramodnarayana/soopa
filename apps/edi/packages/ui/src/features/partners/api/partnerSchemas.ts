import { z } from 'zod';
import type { AS2Partner, Partnership, SFTPPartner } from '../types';

export const AS2PartnerSchema: z.ZodType<AS2Partner> = z.object({
  id: z.string(),
  name: z.string(),
  type: z.literal('AS2'),
  active: z.boolean().optional(),
  as2_id: z.string(),
  is_local: z.boolean(),
  url: z.string().optional(),
});

export const SFTPPartnerSchema: z.ZodType<SFTPPartner> = z.object({
  id: z.string(),
  name: z.string(),
  type: z.literal('SFTP'),
  active: z.boolean().optional(),
  host: z.string(),
  port: z.number(),
  username: z.string(),
  inbound_remote_path: z.string().optional(),
  outbound_remote_path: z.string().optional(),
});

export const PartnerSchema = z.union([AS2PartnerSchema, SFTPPartnerSchema]);

export const PartnersArraySchema = z.array(PartnerSchema);

export const PartnershipSchema: z.ZodType<Partnership> = z.object({
  id: z.string(),
  name: z.string().optional(),
  local_partner_id: z.string(),
  remote_partner_id: z.string(),
  host: z.string().optional(),
  port: z.number().optional(),
  credentials_vault_ref: z.string().optional(),
  mdn_type: z.string(),
  mdn_url: z.string().optional(),
  encryption_algorithm: z.string(),
  signature_algorithm: z.string(),
  active: z.boolean().optional(),
});

export const PartnershipsArraySchema = z.array(PartnershipSchema);
