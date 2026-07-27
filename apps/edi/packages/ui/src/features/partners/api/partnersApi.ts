import type {
  CertificatesExport,
  CreatePartnerPayload,
  CreatePartnershipPayload,
  CreateSftpPartnerPayload,
  Partner,
  Partnership,
} from '../types';
export interface IPartnersRepository {
  deleteCertificateSecret(vaultRef: string): Promise<void>;
  getAS2Partners(): Promise<Partner[]>;
  createAS2Partner(payload: CreatePartnerPayload): Promise<Partner>;
  updateAS2Partner(id: string, payload: UpdatePartnerPayload): Promise<Partner>;
  deleteAS2Partner(id: string): Promise<void>;
  getAS2Partnerships(): Promise<Partnership[]>;
  createAS2Partnership(payload: CreatePartnershipPayload): Promise<Partnership>;
  updateAS2Partnership(id: string, payload: UpdatePartnershipPayload): Promise<Partnership>;
  deleteAS2Partnership(id: string): Promise<void>;
  testAs2PartnershipConnection(
    id: string,
    custom_payload?: string,
  ): Promise<{
    success: boolean;
    mdn_disposition?: string | null;
    reason?: string | null;
    sent_payload?: string | null;
    raw_mdn?: string | null;
  }>;
  exportCertificates(partnerId: string): Promise<CertificatesExport>;
  rotateCertificates(partnerId: string, payload: RotateCertPayload): Promise<Partner>;
  generateCertificate(
    as2Id: string,
  ): Promise<{ public_cert_pem: string; private_key_vault_ref: string }>;
  getTenantPartners(): Promise<Partner[]>;
  createSftpPartner(payload: CreateSftpPartnerPayload): Promise<Partner>;
  updateSftpPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner>;
  deleteSftpPartner(id: string): Promise<void>;
  testSftpConnection(
    payload: Omit<
      CreateSftpPartnerPayload,
      'name' | 'inbound_remote_path' | 'outbound_remote_path'
    >,
  ): Promise<{ success: boolean; reason?: string }>;
  testExistingSftpConnection(
    id: string,
    payload: Omit<
      CreateSftpPartnerPayload,
      'name' | 'inbound_remote_path' | 'outbound_remote_path'
    >,
  ): Promise<{ success: boolean; reason?: string }>;
}

// ─────────────────────────────────────────────
// HTTP Adapter (Adapter layer — swappable)
// ─────────────────────────────────────────────

class HttpPartnersRepository implements IPartnersRepository {
  private readonly headers: Record<string, string>;

  constructor(token: string) {
    this.headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };
  }

  private async request<T>(url: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch(url, { ...init, headers: this.headers, signal: controller.signal });
      if (!res.ok) {
        const contentType = res.headers.get('content-type');
        let errorMessage = res.statusText;
        if (contentType && contentType.includes('application/json')) {
          try {
            const data = (await res.json()) as { detail?: string | Record<string, unknown> };
            errorMessage =
              typeof data.detail === 'string'
                ? data.detail
                : data.detail
                  ? JSON.stringify(data.detail)
                  : JSON.stringify(data);
          } catch {
            errorMessage = await res.text().catch(() => res.statusText);
          }
        } else {
          errorMessage = await res.text().catch(() => res.statusText);
        }
        throw new Error(errorMessage || `HTTP ${res.status}`);
      }
      if (res.status === 204) return undefined;
      return res.json() as Promise<T>;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ── Platform Trading Partners ──────────────
  deleteCertificateSecret(vaultRef: string): Promise<void> {
    return this.request(
      `/api/v1/platform/trading-partners/as2/certificates/secret?vault_ref=${encodeURIComponent(vaultRef)}`,
      { method: 'DELETE' },
    );
  }

  getAS2Partners(): Promise<Partner[]> {
    return this.request('/api/v1/platform/trading-partners/as2/trading-partners');
  }

  createAS2Partner(payload: CreatePartnerPayload): Promise<Partner> {
    return this.request('/api/v1/platform/trading-partners/as2/trading-partners', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateAS2Partner(id: string, payload: UpdatePartnerPayload): Promise<Partner> {
    return this.request(`/api/v1/platform/trading-partners/as2/trading-partners/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deleteAS2Partner(id: string): Promise<void> {
    return this.request(`/api/v1/platform/trading-partners/as2/trading-partners/${id}`, {
      method: 'DELETE',
    });
  }

  // ── Platform Partnerships ──────────────────
  getAS2Partnerships(): Promise<Partnership[]> {
    return this.request('/api/v1/platform/trading-partners/as2/partnerships');
  }

  createAS2Partnership(payload: CreatePartnershipPayload): Promise<Partnership> {
    return this.request('/api/v1/platform/trading-partners/as2/partnerships', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateAS2Partnership(id: string, payload: UpdatePartnershipPayload): Promise<Partnership> {
    return this.request(`/api/v1/platform/trading-partners/as2/partnerships/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deleteAS2Partnership(id: string): Promise<void> {
    return this.request(`/api/v1/platform/trading-partners/as2/partnerships/${id}`, {
      method: 'DELETE',
    });
  }

  testAs2PartnershipConnection(
    id: string,
    custom_payload?: string,
  ): Promise<{
    success: boolean;
    mdn_disposition?: string | null;
    reason?: string | null;
    sent_payload?: string | null;
    raw_mdn?: string | null;
  }> {
    return this.request(`/api/v1/platform/trading-partners/as2/partnerships/${id}/test`, {
      method: 'POST',
      body: custom_payload ? JSON.stringify({ custom_payload }) : undefined,
    });
  }

  // ── Certificates ───────────────────────────
  exportCertificates(partnerId: string): Promise<CertificatesExport> {
    return this.request(`/api/v1/trading-partners/as2/${partnerId}/certificates/export`);
  }

  rotateCertificates(partnerId: string, payload: RotateCertPayload): Promise<Partner> {
    return this.request(`/api/v1/trading-partners/as2/${partnerId}/certificates/rotate`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  generateCertificate(
    as2Id: string,
  ): Promise<{ public_cert_pem: string; private_key_vault_ref: string }> {
    return this.request(`/api/v1/platform/trading-partners/as2/certificates/generate`, {
      method: 'POST',
      body: JSON.stringify({ as2_id: as2Id }),
    });
  }

  // ── Tenant Partners ────────────────────────
  async getTenantPartners(): Promise<Partner[]> {
    const data = await this.request<Array<Partner & { partner_id?: string }>>(
      '/api/v1/trading-partners',
    );
    return data.map((p) => ({ ...p, id: p.partner_id || p.id }));
  }

  createSftpPartner(payload: CreateSftpPartnerPayload): Promise<Partner> {
    return this.request('/api/v1/trading-partners/sftp', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateSftpPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner> {
    return this.request(`/api/v1/trading-partners/sftp/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deleteSftpPartner(id: string): Promise<void> {
    return this.request(`/api/v1/trading-partners/sftp/${id}`, { method: 'DELETE' });
  }

  testSftpConnection(
    payload: Omit<
      CreateSftpPartnerPayload,
      'name' | 'inbound_remote_path' | 'outbound_remote_path'
    >,
  ): Promise<{ success: boolean; reason?: string }> {
    return this.request('/api/v1/trading-partners/sftp/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  testExistingSftpConnection(
    id: string,
    payload: Omit<
      CreateSftpPartnerPayload,
      'name' | 'inbound_remote_path' | 'outbound_remote_path'
    >,
  ): Promise<{ success: boolean; reason?: string }> {
    return this.request(`/api/v1/trading-partners/${id}/sftp/test`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
}

/**
 * Factory — injects the token once; hooks call this, not the class directly.
 * Swap the factory in tests to return a stub that implements IPartnersRepository.
 */
export function createPartnersRepository(token: string): IPartnersRepository {
  return new HttpPartnersRepository(token);
}
