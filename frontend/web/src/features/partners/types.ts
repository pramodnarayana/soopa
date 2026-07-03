// ─────────────────────────────────────────────
// Domain Enums
// ─────────────────────────────────────────────

export type PartnerType = 'AS2' | 'SFTP';

// ─────────────────────────────────────────────
// Domain Entities
// ─────────────────────────────────────────────

export interface Partner {
  id: string;
  name: string;
  type: PartnerType;
  host?: string;
  as2_id?: string;
  username?: string;
  is_local?: boolean;
  url?: string;
  active?: boolean;
}

export interface Partnership {
  id: string;
  name?: string;
  local_partner_id: string;
  remote_partner_id: string;
  host?: string;
  port?: number;
  credentials_vault_ref?: string;
  mdn_type: string;
  mdn_url?: string;
  encryption_algorithm: string;
  signature_algorithm: string;
  edi_version?: string | null;
  active?: boolean;
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
  remote_path?: string;
  credentials_vault_ref?: string;
}

export interface CreatePartnershipPayload {
  name?: string;
  local_partner_id: string;
  remote_partner_id: string;
  mdn_type: string;
  encryption_algorithm: string;
  signature_algorithm: string;
  edi_version?: string;
  mdn_url?: string;
}

export interface UpdatePartnershipPayload {
  name?: string;
  credentials_vault_ref?: string;
  mdn_type?: string;
  mdn_url?: string;
  encryption_algorithm?: string;
  signature_algorithm?: string;
  edi_version?: string;
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
