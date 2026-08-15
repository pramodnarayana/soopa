import type { CreateWebhookPayload, UpdateWebhookPayload, Webhook } from '../types';

/**
 * Platform-level HTTP repository for Webhook CRUD operations.
 * Communicates with the UCP API: GET/POST/PATCH/DELETE /api/v1/tenants/:tenantId/webhooks
 *
 * This repository is intentionally decoupled from any EDI context or provider.
 * It can be used by any app in the monorepo (IDP, EDI, IP, etc.).
 */
export class HttpWebhookRepository {
  private readonly baseUrl: string;
  private readonly tenantId: string;
  private readonly token: string;

  constructor(baseUrl: string, tenantId: string, token: string) {
    this.baseUrl = baseUrl;
    this.tenantId = tenantId;
    this.token = token;
  }

  private get apiRoot(): string {
    return `${this.baseUrl}/tenants/${this.tenantId}/webhooks`;
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
          // ignore parse errors, use statusText
        }
        throw new Error(message);
      }

      if (res.status === 204) return undefined as unknown as T;
      return (await res.json()) as T;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  getAll(): Promise<Webhook[]> {
    return this.request<Webhook[]>('');
  }

  create(payload: CreateWebhookPayload): Promise<Webhook> {
    return this.request<Webhook>('', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  update(id: string, payload: UpdateWebhookPayload): Promise<Webhook> {
    return this.request<Webhook>(`/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  delete(id: string): Promise<void> {
    return this.request<void>(`/${id}`, { method: 'DELETE' });
  }
}
