import { getApiUrl } from './config';

export const HttpMethod = {
  GET: 'GET',
  POST: 'POST',
  PUT: 'PUT',
  PATCH: 'PATCH',
  DELETE: 'DELETE',
} as const;
export type HttpMethodValue = (typeof HttpMethod)[keyof typeof HttpMethod];

export type QueryParamsRecord = Readonly<
  Record<string, string | number | boolean | null | undefined>
>;

export interface DashboardFetchOptions {
  readonly method?: string;
  readonly params?: QueryParamsRecord;
  readonly headers?: HeadersInit;
  readonly signal?: AbortSignal;
  readonly body?: unknown;
}

export type DashboardRequestConfig = Omit<DashboardFetchOptions, 'method' | 'body'>;

export interface UcpApiClientPort {
  readonly httpClient?: unknown;
  request<T>(endpoint: string, options?: DashboardFetchOptions): Promise<T>;
  get<T>(endpoint: string, options?: DashboardRequestConfig): Promise<T>;
  post<T>(endpoint: string, body?: unknown, options?: DashboardRequestConfig): Promise<T>;
  put<T>(endpoint: string, body?: unknown, options?: DashboardRequestConfig): Promise<T>;
  patch<T>(endpoint: string, body?: unknown, options?: DashboardRequestConfig): Promise<T>;
  delete<T>(endpoint: string, options?: DashboardRequestConfig): Promise<T>;
}

const VALID_HTTP_METHODS: ReadonlySet<string> = new Set(Object.values(HttpMethod));

export function isHttpMethodValue(candidate: string): candidate is HttpMethodValue {
  return VALID_HTTP_METHODS.has(candidate);
}

export function parseHttpMethod(raw?: string): HttpMethodValue {
  const upper = raw?.toUpperCase();
  if (upper && isHttpMethodValue(upper)) {
    return upper;
  }
  return HttpMethod.GET;
}

function buildUrl(baseUrl: string, endpoint: string, params?: QueryParamsRecord): string {
  const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  // If base is a fully qualified URL, parse with URL constructor; otherwise append relative path
  if (cleanBase.startsWith('http://') || cleanBase.startsWith('https://')) {
    const url = new URL(`${cleanBase}${cleanEndpoint}`);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.append(key, String(value));
        }
      }
    }
    return url.toString();
  }

  const queryParts: string[] = [];
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        queryParts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
      }
    }
  }
  const queryString = queryParts.length > 0 ? `?${queryParts.join('&')}` : '';
  return `${cleanBase}${cleanEndpoint}${queryString}`;
}

export interface CreateScopedUcpApiClientOptions {
  readonly getToken: () => string | null | undefined;
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createScopedUcpApiClient(
  options: CreateScopedUcpApiClientOptions,
): UcpApiClientPort {
  const fetchFn = options.fetchImpl ?? globalThis.fetch;
  const baseUrl = options.baseUrl ?? getApiUrl('/api/v1');

  const execute = async <T>(
    method: HttpMethodValue,
    endpoint: string,
    body?: unknown,
    config?: DashboardRequestConfig,
  ): Promise<T> => {
    const token = options.getToken();
    const headers = new Headers(config?.headers);
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    let payload: BodyInit | undefined;
    if (body !== undefined && body !== null) {
      if (typeof body === 'string') {
        payload = body;
        if (!headers.has('Content-Type')) {
          headers.set('Content-Type', 'application/json');
        }
      } else if (
        body instanceof FormData ||
        body instanceof Blob ||
        body instanceof URLSearchParams
      ) {
        payload = body;
      } else {
        payload = JSON.stringify(body);
        if (!headers.has('Content-Type')) {
          headers.set('Content-Type', 'application/json');
        }
      }
    }

    const url = buildUrl(baseUrl, endpoint, config?.params);
    const response = await fetchFn(url, {
      method,
      headers,
      signal: config?.signal,
      body: method !== HttpMethod.GET ? payload : undefined,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `HTTP ${response.status} ${response.statusText}`);
    }

    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return (await response.json()) as T;
    }
    return (await response.text()) as unknown as T;
  };

  return {
    httpClient: { execute },

    async request<T>(endpoint: string, reqOptions: DashboardFetchOptions = {}): Promise<T> {
      const method = parseHttpMethod(reqOptions.method);
      return execute<T>(method, endpoint, reqOptions.body, {
        params: reqOptions.params,
        headers: reqOptions.headers,
        signal: reqOptions.signal,
      });
    },

    async get<T>(endpoint: string, reqOptions?: DashboardRequestConfig): Promise<T> {
      return execute<T>(HttpMethod.GET, endpoint, undefined, reqOptions);
    },

    async post<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return execute<T>(HttpMethod.POST, endpoint, body, reqOptions);
    },

    async put<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return execute<T>(HttpMethod.PUT, endpoint, body, reqOptions);
    },

    async patch<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return execute<T>(HttpMethod.PATCH, endpoint, body, reqOptions);
    },

    async delete<T>(endpoint: string, reqOptions?: DashboardRequestConfig): Promise<T> {
      return execute<T>(HttpMethod.DELETE, endpoint, undefined, reqOptions);
    },
  };
}
