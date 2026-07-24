import type { CreateWebhookEndpointPayload, Webhook } from '../types';

class HttpWebhooksRepository {
  private token: string;

  constructor(token: string) {
    this.token = token;
  }

  private async fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`/api/v1${path}`, {
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
        const errData = (await res.json()) as { detail?: string | Array<{ msg?: string }> };
        errMessage =
          typeof errData.detail === 'string'
            ? errData.detail
            : errData.detail?.[0]?.msg || errMessage;
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
    const raw =
      await this.fetchApi<
        Array<{
          partner_id?: string;
          id?: string;
          tenant_id: string;
          name: string;
          type: string;
          status: string;
          url: string;
        }>
      >('/webhooks');
    return raw.map((p) => ({
      id: p.partner_id,
      tenant_id: p.tenant_id,
      name: p.name,
      type: p.type,
      status: p.status,
      url: p.url,
    }));
  }

  async createWebhook(payload: CreateWebhookEndpointPayload): Promise<Webhook> {
    const raw = await this.fetchApi<{
      partner_id?: string;
      id?: string;
      tenant_id: string;
      name: string;
      type: string;
      status: string;
      url: string;
    }>('/webhooks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return {
      id: raw.partner_id,
      tenant_id: raw.tenant_id,
      name: raw.name,
      type: raw.type,
      status: raw.status,
      url: raw.url,
    };
  }

  async updateWebhookStatus(webhookId: string, active: boolean): Promise<Webhook> {
    const raw = await this.fetchApi<{
      partner_id?: string;
      id?: string;
      tenant_id: string;
      name: string;
      type: string;
      status: string;
      url: string;
    }>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify({ active }),
    });
    return {
      id: raw.partner_id,
      tenant_id: raw.tenant_id,
      name: raw.name,
      type: raw.type,
      status: raw.status,
      url: raw.url,
    };
  }

  async updateWebhook(
    webhookId: string,
    payload: { name?: string; url?: string },
  ): Promise<Webhook> {
    const raw = await this.fetchApi<{
      partner_id?: string;
      id?: string;
      tenant_id: string;
      name: string;
      type: string;
      status: string;
      url: string;
    }>(`/webhooks/${webhookId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    return {
      id: raw.partner_id,
      tenant_id: raw.tenant_id,
      name: raw.name,
      type: raw.type,
      status: raw.status,
      url: raw.url,
    };
  }

  async deleteWebhook(webhookId: string): Promise<void> {
    await this.fetchApi<void>(`/webhooks/${webhookId}`, {
      method: 'DELETE',
    });
  }
}

export function createWebhooksRepository(token: string) {
  return new HttpWebhooksRepository(token);
}
