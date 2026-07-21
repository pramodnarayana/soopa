import type { ApiToken, ApiTokenCreated, CreateApiTokenPayload } from '../types';

class HttpApiTokenRepository {
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
        let errorMessage = res.statusText;
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          try {
            const data = await res.json();
            errorMessage = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
          } catch {
            errorMessage = await res.text().catch(() => res.statusText);
          }
        } else {
          errorMessage = await res.text().catch(() => res.statusText);
        }
        throw new Error(errorMessage || `HTTP ${res.status}`);
      }
      if (res.status === 204) return undefined as unknown as T;
      return res.json() as Promise<T>;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  getApiTokens(): Promise<{ tokens: ApiToken[] }> {
    return this.request('/api/v1/developers/tokens');
  }

  createApiToken(payload: CreateApiTokenPayload): Promise<ApiTokenCreated> {
    return this.request('/api/v1/developers/tokens', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateApiToken(id: string, data: { name?: string; active?: boolean }): Promise<void> {
    return this.request(`/api/v1/developers/tokens/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  deleteApiToken(id: string): Promise<void> {
    return this.request(`/api/v1/developers/tokens/${id}`, {
      method: 'DELETE',
    });
  }
}

export function createApiTokenRepository(token: string) {
  return new HttpApiTokenRepository(token);
}
