import type {
  CreateInboundRoutePayload,
  CreateOutboundRoutePayload,
  RouteItem,
  UpdateRoutePayload,
} from '../types';

export interface IRoutesRepository {
  getRoutes(): Promise<RouteItem[]>;
  createInboundRoute(payload: CreateInboundRoutePayload): Promise<void>;
  createOutboundRoute(payload: CreateOutboundRoutePayload): Promise<void>;
  updateRoute(
    routeId: string,
    direction: 'INBOUND' | 'OUTBOUND',
    payload: UpdateRoutePayload,
  ): Promise<void>;
  deleteRoute(routeId: string, direction: 'INBOUND' | 'OUTBOUND'): Promise<void>;
}

class HttpRoutesRepository implements IRoutesRepository {
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
      let errorMessage = res.statusText;
      try {
        const data = (await res.json()) as { detail?: string | Record<string, unknown> };
        errorMessage =
          typeof data.detail === 'string'
            ? data.detail
            : data.detail
              ? JSON.stringify(data.detail)
              : JSON.stringify(data);
      } catch {
        // Use status text
      }
      throw new Error(errorMessage || 'API request failed');
    }
    const text = await res.text();
    if (!text) return {} as T;
    return JSON.parse(text) as T;
  }

  getRoutes(): Promise<RouteItem[]> {
    return this.request('/api/v1/routes');
  }

  createInboundRoute(payload: CreateInboundRoutePayload): Promise<void> {
    return this.request('/api/v1/routes/inbound', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  createOutboundRoute(payload: CreateOutboundRoutePayload): Promise<void> {
    return this.request('/api/v1/routes/outbound', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateRoute(
    routeId: string,
    direction: 'INBOUND' | 'OUTBOUND',
    payload: UpdateRoutePayload,
  ): Promise<void> {
    const endpoint =
      direction === 'INBOUND'
        ? `/api/v1/routes/inbound/${routeId}`
        : `/api/v1/routes/outbound/${routeId}`;
    return this.request(endpoint, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  deleteRoute(routeId: string, direction: 'INBOUND' | 'OUTBOUND'): Promise<void> {
    const ep = direction === 'INBOUND' ? 'inbound' : 'outbound';
    return this.request(`/api/v1/routes/${ep}/${routeId}`, {
      method: 'DELETE',
    });
  }
}

export function createRoutesRepository(token: string): IRoutesRepository {
  return new HttpRoutesRepository(token);
}
