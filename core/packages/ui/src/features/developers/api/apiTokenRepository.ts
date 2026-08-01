import type { ApiToken, ApiTokenCreated, CreateApiTokenPayload } from '../types';

/**
 * Platform-level HTTP repository for API Token CRUD operations.
 * Communicates with UCP API: /api/v1/tenants/:tenantId/tokens
 *
 * Decoupled from EDI domain — usable by any app in the monorepo.
 */
export class HttpApiTokenRepository {
  private readonly baseUrl: string;
  private readonly tenantId: string;
  private readonly token: string;

  constructor(baseUrl: string, tenantId: string, token: string) {
    this.baseUrl = baseUrl;
    this.tenantId = tenantId;
    this.token = token;
  }

  private get apiRoot(): string {
    return `${this.baseUrl}/tenants/${this.tenantId}/tokens`;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15_000);

    try {
      const res = await fetch(`${this.apiRoot}${path}`, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.token}`,
          ...init?.headers,
        },
        signal: controller.signal,
      });

      if (!res.ok) {
        let message = res.statusText;
        try {
          const err = (await res.json()) as { message?: string | string[]; detail?: string };
          message = Array.isArray(err.message)
            ? err.message[0]
            : (err.message ?? err.detail ?? message);
        } catch {
          // ignore parse errors
        }
        throw new Error(message);
      }

      if (res.status === 204) return undefined as unknown as T;
      return (await res.json()) as T;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  getAll(): Promise<ApiToken[]> {
    return this.request<ApiToken[]>('');
  }

  create(payload: CreateApiTokenPayload): Promise<ApiTokenCreated> {
    return this.request<ApiTokenCreated>('', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  update(id: string, data: { name?: string; active?: boolean }): Promise<void> {
    return this.request<void>(`/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  delete(id: string): Promise<void> {
    return this.request<void>(`/${id}`, { method: 'DELETE' });
  }
}
