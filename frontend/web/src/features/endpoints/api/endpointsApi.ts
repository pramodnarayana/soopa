import type { Endpoint, CreateWebhookEndpointPayload } from '../types';

export interface IEndpointsRepository {
  getTenantEndpoints(): Promise<Endpoint[]>;
  createWebhookEndpoint(payload: CreateWebhookEndpointPayload): Promise<Endpoint>;
}

export class HttpEndpointsRepository implements IEndpointsRepository {
  private token: string;

  constructor(token: string) {
    this.token = token;
  }

  private async fetchApi(path: string, options: RequestInit = {}) {
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
        const errData = await res.json();
        errMessage = typeof errData.detail === 'string'
          ? errData.detail
          : errData.detail?.[0]?.msg || errMessage;
      } catch {
        errMessage = res.statusText;
      }
      throw new Error(errMessage);
    }

    if (res.status === 204) {
      return null;
    }
    return res.json();
  }

  async getTenantEndpoints(): Promise<Endpoint[]> {
    const raw = await this.fetchApi('/webhooks');
    // Transform PartnerResponse from backend into frontend Endpoint
    return raw.map((p: any) => ({
      id: p.partner_id,
      tenant_id: p.tenant_id,
      name: p.name,
      type: p.type,
      status: p.status,
    }));
  }

  async createWebhookEndpoint(payload: CreateWebhookEndpointPayload): Promise<Endpoint> {
    const raw = await this.fetchApi('/webhooks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return {
      id: raw.partner_id,
      tenant_id: raw.tenant_id,
      name: raw.name,
      type: raw.type,
      status: raw.status,
    };
  }
}

export function createEndpointsRepository(token: string): IEndpointsRepository {
  return new HttpEndpointsRepository(token);
}
