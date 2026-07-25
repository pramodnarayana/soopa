import type { CreateWebhookEndpointPayload, Webhook } from '../types';

class HttpWebhooksRepository {
  private token: string;
  private tenantId: string;
  private baseUrl: string;

  constructor(token: string, tenantId: string, baseUrl: string = 'http://localhost:3000') {
    this.token = token;
    this.tenantId = tenantId;
    this.baseUrl = baseUrl;
  }

  private async fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.baseUrl}/tenants/${this.tenantId}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
        ...options.headers,
      },
    });

    if (!res.ok) {
      let errMessage = 'API Request Failed';
      try {
        const errData = (await res.json()) as { message?: string | Array<string>; detail?: string };
        errMessage = errData.message
          ? Array.isArray(errData.message)
            ? errData.message[0]
            : errData.message
          : errData.detail || errMessage;
      } catch {
        errMessage = res.statusText;
      }
      throw new Error(errMessage);
    }

    if (res.status === 204) {
      return null as unknown as T;
    }
    return res.json() as Promise<T>;
  }

  async getTenantWebhooks(): Promise<Webhook[]> {
    return this.fetchApi<Webhook[]>('/webhooks');
  }

  async createWebhook(payload: CreateWebhookEndpointPayload): Promise<Webhook> {
    return this.fetchApi<Webhook>('/webhooks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateWebhookStatus(webhookId: string, active: boolean): Promise<Webhook> {
    return this.fetchApi<Webhook>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify({ active }),
    });
  }

  async updateWebhook(
    webhookId: string,
    payload: { name?: string; url?: string },
  ): Promise<Webhook> {
    return this.fetchApi<Webhook>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async deleteWebhook(webhookId: string): Promise<void> {
    await this.fetchApi<void>(`/webhooks/${webhookId}`, {
      method: 'DELETE',
    });
  }
}

export function createWebhooksRepository(token: string, tenantId: string, baseUrl?: string) {
  return new HttpWebhooksRepository(token, tenantId, baseUrl);
}
