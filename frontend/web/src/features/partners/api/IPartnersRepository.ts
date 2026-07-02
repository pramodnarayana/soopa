import type {
  Partner,
  Partnership,
  CertificatesExport,
  CreatePartnerPayload,
  UpdatePartnerPayload,
  CreatePartnershipPayload,
  UpdatePartnershipPayload,
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

  // Certificates
  exportCertificates(partnerId: string): Promise<CertificatesExport>;
  rotateCertificates(partnerId: string, payload: RotateCertPayload): Promise<Partner>;

  // Tenant Partners
  getTenantPartners(): Promise<Partner[]>;
  updateSftpPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner>;
  deleteSftpPartner(id: string): Promise<void>;
}
