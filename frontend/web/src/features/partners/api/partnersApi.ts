import type { IPartnersRepository } from './IPartnersRepository';
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
    const res = await fetch(url, { ...init, headers: this.headers });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new Error(detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return undefined as unknown as T;
    return res.json() as Promise<T>;
  }

  // ── Platform Trading Partners ──────────────
  getPlatformPartners(): Promise<Partner[]> {
    return this.request('/api/v1/platform/partners/as2/trading-partners');
  }

  createPlatformPartner(payload: CreatePartnerPayload): Promise<Partner> {
    return this.request('/api/v1/platform/partners/as2/trading-partners', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updatePlatformPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner> {
    return this.request(`/api/v1/platform/partners/as2/trading-partners/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deletePlatformPartner(id: string): Promise<void> {
    return this.request(`/api/v1/platform/partners/as2/trading-partners/${id}`, {
      method: 'DELETE',
    });
  }

  // ── Platform Partnerships ──────────────────
  getPlatformPartnerships(): Promise<Partnership[]> {
    return this.request('/api/v1/platform/partners/as2/partnerships');
  }

  createPlatformPartnership(payload: CreatePartnershipPayload): Promise<Partnership> {
    return this.request('/api/v1/platform/partners/as2/partnerships', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updatePlatformPartnership(id: string, payload: UpdatePartnershipPayload): Promise<Partnership> {
    return this.request(`/api/v1/platform/partners/as2/partnerships/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deletePlatformPartnership(id: string): Promise<void> {
    return this.request(`/api/v1/platform/partners/as2/partnerships/${id}`, {
      method: 'DELETE',
    });
  }

  // ── Certificates ───────────────────────────
  exportCertificates(partnerId: string): Promise<CertificatesExport> {
    return this.request(
      `/api/v1/partners/as2/trading-partners/${partnerId}/certificates/export`,
    );
  }

  rotateCertificates(partnerId: string, payload: RotateCertPayload): Promise<Partner> {
    return this.request(
      `/api/v1/partners/as2/trading-partners/${partnerId}/certificates/rotate`,
      { method: 'PUT', body: JSON.stringify(payload) },
    );
  }

  // ── Tenant Partners ────────────────────────
  getTenantPartners(): Promise<Partner[]> {
    return this.request('/api/v1/partners');
  }

  updateSftpPartner(id: string, payload: UpdatePartnerPayload): Promise<Partner> {
    return this.request(`/api/v1/partners/sftp/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  deleteSftpPartner(id: string): Promise<void> {
    return this.request(`/api/v1/partners/sftp/${id}`, { method: 'DELETE' });
  }
}

/**
 * Factory — injects the token once; hooks call this, not the class directly.
 * Swap the factory in tests to return a stub that implements IPartnersRepository.
 */
export function createPartnersRepository(token: string): IPartnersRepository {
  return new HttpPartnersRepository(token);
}
