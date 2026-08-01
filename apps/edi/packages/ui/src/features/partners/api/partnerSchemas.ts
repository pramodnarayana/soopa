import { z } from 'zod';
import type { AS2Partner, AS2Partnership, SFTPPartner } from '../types';

export const AS2PartnerSchema: z.ZodType<AS2Partner> = z.object({
  id: z.string(),
  name: z.string(),
  type: z.literal('AS2'),
  active: z.boolean().nullish(),
  as2_id: z.string(),
  is_local: z.boolean(),
  url: z.string().nullish(),
});

export const SFTPPartnerSchema: z.ZodType<SFTPPartner> = z.object({
  id: z.string(),
  name: z.string(),
  type: z.literal('SFTP'),
  active: z.boolean().nullish(),
  host: z.string(),
  port: z.number(),
  username: z.string(),
  inbound_remote_path: z.string().nullish(),
  outbound_remote_path: z.string().nullish(),
});

export const PartnerSchema = z.union([AS2PartnerSchema, SFTPPartnerSchema]);

export const PartnersArraySchema = z.array(PartnerSchema);

export const AS2PartnershipSchema: z.ZodType<AS2Partnership> = z.object({
  id: z.string(),
  name: z.string().nullish(),
  local_partner_id: z.string(),
  remote_partner_id: z.string(),
  credentials_vault_ref: z.string().nullish(),
  mdn_type: z.string(),
  mdn_url: z.string().nullish(),
  encryption_algorithm: z.string(),
  signature_algorithm: z.string(),
  active: z.boolean().nullish(),
});

export const AS2PartnershipsArraySchema = z.array(AS2PartnershipSchema);
