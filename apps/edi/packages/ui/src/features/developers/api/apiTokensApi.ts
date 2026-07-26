import type { ApiToken, ApiTokenCreated, CreateApiTokenPayload } from '../types';

class HttpApiTokenRepository {
  private token: string;
  private tenantId: string;
  private baseUrl: string;

  constructor(token: string, tenantId: string, baseUrl: string) {
    this.token = token;
    this.tenantId = tenantId;
    this.baseUrl = baseUrl;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch(`${this.baseUrl}/tenants/${this.tenantId}${path}`, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.token}`,
          ...(init?.headers || {}),
        },
        signal: controller.signal,
      });
      if (!res.ok) {
        let errorMessage = res.statusText;
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          try {
            const data = (await res.json()) as {
              message?: string | Array<string>;
              detail?: string;
            };
            errorMessage = data.message
              ? Array.isArray(data.message)
                ? data.message[0]
                : data.message
              : data.detail || errorMessage;
          } catch {
            errorMessage = await res.text().catch(() => res.statusText);
          }
        } else {
          errorMessage = await res.text().catch(() => res.statusText);
        }
        throw new Error(errorMessage || `HTTP ${res.status}`);
      }
      if (res.status === 204) return undefined as unknown as T;
      const jsonData = await res.json() as T;
      return jsonData;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  getApiTokens(): Promise<ApiToken[]> {
    return this.request<ApiToken[]>('/tokens');
  }

  createApiToken(payload: CreateApiTokenPayload): Promise<ApiTokenCreated> {
    return this.request<ApiTokenCreated>('/tokens', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateApiToken(id: string, data: { name?: string; active?: boolean }): Promise<void> {
    return this.request<void>(`/tokens/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  deleteApiToken(id: string): Promise<void> {
    return this.request<void>(`/tokens/${id}`, {
      method: 'DELETE',
    });
  }
}

export function createApiTokenRepository(token: string, tenantId: string, baseUrl: string) {
  return new HttpApiTokenRepository(token, tenantId, baseUrl);
}
