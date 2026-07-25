import type { CreateWebhookEndpointPayload, Webhook } from '../types';

class HttpWebhooksRepository {
  private token: string;
  private tenantId: string;
  private baseUrl: string;

  constructor(token: string, tenantId: string, baseUrl: string) {
    this.token = token;
    this.tenantId = tenantId;
    this.baseUrl = baseUrl;
  }

  private async fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch(`${this.baseUrl}/tenants/${this.tenantId}${path}`, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.token}`,
          ...options.headers,
        },
        signal: controller.signal,
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
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async getTenantWebhooks(): Promise<Webhook[]> {
    const rawWebhooks = await this.fetchApi<
      Array<{ id: string; name: string; url: string; active: boolean; createdAt: string }>
    >('/webhooks');
    return rawWebhooks.map((w) => ({
      id: w.id,
      name: w.name,
      url: w.url,
      type: 'WEBHOOK' as const,
      status: w.active ? ('ACTIVE' as const) : ('INACTIVE' as const),
      tenant_id: parseInt(this.tenantId, 10),
    }));
  }

  async createWebhook(payload: CreateWebhookEndpointPayload): Promise<Webhook> {
    const rawWebhook = await this.fetchApi<{
      id: string;
      name: string;
      url: string;
      active: boolean;
      createdAt: string;
    }>('/webhooks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return {
      id: rawWebhook.id,
      name: rawWebhook.name,
      url: rawWebhook.url,
      type: 'WEBHOOK',
      status: rawWebhook.active ? 'ACTIVE' : 'INACTIVE',
      tenant_id: parseInt(this.tenantId, 10),
    };
  }

  async updateWebhookStatus(webhookId: string, active: boolean): Promise<Webhook> {
    const rawWebhook = await this.fetchApi<{
      id: string;
      name: string;
      url: string;
      active: boolean;
      createdAt: string;
    }>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify({ active }),
    });
    return {
      id: rawWebhook.id,
      name: rawWebhook.name,
      url: rawWebhook.url,
      type: 'WEBHOOK',
      status: rawWebhook.active ? 'ACTIVE' : 'INACTIVE',
      tenant_id: parseInt(this.tenantId, 10),
    };
  }

  async updateWebhook(
    webhookId: string,
    payload: { name?: string; url?: string },
  ): Promise<Webhook> {
    const rawWebhook = await this.fetchApi<{
      id: string;
      name: string;
      url: string;
      active: boolean;
      createdAt: string;
    }>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    return {
      id: rawWebhook.id,
      name: rawWebhook.name,
      url: rawWebhook.url,
      type: 'WEBHOOK',
      status: rawWebhook.active ? 'ACTIVE' : 'INACTIVE',
      tenant_id: parseInt(this.tenantId, 10),
    };
  }

  async deleteWebhook(webhookId: string): Promise<void> {
    await this.fetchApi<void>(`/webhooks/${webhookId}`, {
      method: 'DELETE',
    });
  }
}

export function createWebhooksRepository(token: string, tenantId: string, baseUrl: string) {
  return new HttpWebhooksRepository(token, tenantId, baseUrl);
}
