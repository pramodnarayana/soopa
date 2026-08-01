// ─────────────────────────────────────────────
// Domain Enums
// ─────────────────────────────────────────────

export type PartnerType = 'AS2' | 'SFTP';

// ─────────────────────────────────────────────
// Domain Entities
// ─────────────────────────────────────────────

export interface BasePartner {
  id: string;
  name: string;
  type: PartnerType;
  active?: boolean | null;
}

export interface AS2Partner extends BasePartner {
  type: 'AS2';
  as2_id: string;
  is_local: boolean;
  url?: string | null;
}

export interface SFTPPartner extends BasePartner {
  type: 'SFTP';
  host: string;
  port: number;
  username: string;
  inbound_remote_path?: string | null;
  outbound_remote_path?: string | null;
}

export type Partner = AS2Partner | SFTPPartner;

export interface AS2Partnership {
  id: string;

  name?: string | null;
  local_partner_id: string;
  remote_partner_id: string;
  credentials_vault_ref?: string | null;
  mdn_type: string;
  mdn_url?: string | null;
  encryption_algorithm: string;
  signature_algorithm: string;

  active?: boolean | null;
}

export interface CertificatesExport {
  public_cert_pem?: string;
  prev_public_cert_pem?: string;
  private_key_pem?: string;
  prev_private_key_pem?: string;
}

// ─────────────────────────────────────────────
// Command / Request DTOs
// ─────────────────────────────────────────────

export interface CreatePartnerPayload {
  name: string;
  type: PartnerType;
  as2_id: string;
  is_local: boolean;
  url?: string;
  public_cert_pem?: string;
  private_key_vault_ref?: string;
  private_key_pem?: string;
}

export interface UpdatePartnerPayload {
  name?: string;
  as2_id?: string;
  is_local?: boolean;
  url?: string;
  public_cert_pem?: string;
  public_cert_vault_ref?: string;
  private_key_vault_ref?: string;
  active?: boolean;
  // SFTP-specific
  host?: string;
  port?: number;
  username?: string;
  inbound_remote_path?: string;
  outbound_remote_path?: string;
  password?: string;
  credentials_vault_ref?: string;
}

export interface CreateAS2PartnershipPayload {
  name?: string;
  local_partner_id: string;
  remote_partner_id: string;
  mdn_type: string;
  encryption_algorithm: string;
  signature_algorithm: string;

  mdn_url?: string;
}

export interface CreateSftpPartnerPayload {
  name: string;
  host: string;
  port: number;
  username: string;
  inbound_remote_path?: string;
  outbound_remote_path?: string;
  password?: string;
  credentials_vault_ref?: string;
}

export interface UpdateAS2PartnershipPayload {
  name?: string;
  credentials_vault_ref?: string;
  mdn_type?: string;
  mdn_url?: string;
  encryption_algorithm?: string;
  signature_algorithm?: string;

  advanced_flags?: Record<string, unknown>;
  active?: boolean;
}

export type RotateCertPayload =
  | {
      action: 'generate';
    }
  | {
      action: 'upload';
      public_cert_pem: string;
      private_key_pem?: string;
    };
