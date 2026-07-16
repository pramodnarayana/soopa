import type {
  Partner,
  Partnership,
  CertificatesExport,
  CreatePartnerPayload,
  UpdatePartnerPayload,
  CreatePartnershipPayload,
  UpdatePartnershipPayload,
  CreateSftpPartnerPayload,
  RotateCertPayload,
} from '../types';

/**
 * Port: defines ALL data operations the partners feature needs.
 * The concrete HTTP adapter (`partnersApi`) implements this.
 * In tests, swap in a fake/stub that also implements this interface.
 */
export interface IPartnersRepository {
  // Platform Trading Partners
  getPlatformPartners(): Promise<Partner[]>;
  createPlatformPartner(payload: CreatePartnerPayload): Promise<Partner>;
  updatePlatformPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner>;
  deletePlatformPartner(id: string): Promise<void>;

  // Platform Partnerships
  getPlatformPartnerships(): Promise<Partnership[]>;
  createPlatformPartnership(payload: CreatePartnershipPayload): Promise<Partnership>;
  updatePlatformPartnership(id: string, payload: UpdatePartnershipPayload): Promise<Partnership>;
  deletePlatformPartnership(id: string): Promise<void>;
  testAs2PartnershipConnection(id: string, custom_payload?: string): Promise<{ success: boolean; mdn_disposition?: string | null; reason?: string | null; sent_payload?: string | null; raw_mdn?: string | null }>;

  // Certificates
  exportCertificates(partnerId: string): Promise<CertificatesExport>;
  rotateCertificates(partnerId: string, payload: RotateCertPayload): Promise<Partner>;
  generateCertificate(as2Id: string): Promise<{ public_cert_pem: string; private_key_vault_ref: string }>;

  // Tenant Partners
  getTenantPartners(): Promise<Partner[]>;
  createSftpPartner(payload: CreateSftpPartnerPayload): Promise<Partner>;
  updateSftpPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner>;
  deleteSftpPartner(id: string): Promise<void>;
  testSftpConnection(payload: Omit<CreateSftpPartnerPayload, 'name' | 'inbound_remote_path' | 'outbound_remote_path'>): Promise<{ success: boolean; reason?: string }>;
  testExistingSftpConnection(id: string, payload: Omit<CreateSftpPartnerPayload, 'name' | 'inbound_remote_path' | 'outbound_remote_path'>): Promise<{ success: boolean; reason?: string }>;
}
