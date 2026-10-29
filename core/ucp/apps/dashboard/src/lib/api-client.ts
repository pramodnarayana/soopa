import {
  FetchHttpClientAdapter,
  type HttpClientPort,
  HttpMethod,
  type HttpMethodValue,
  type HttpRequestOptions,
  type QueryParamsRecord,
  StructuredJsonLoggerAdapter,
  unwrapOrThrow,
} from '@soopa/ui';
import { getApiUrl } from './config';

export interface DashboardFetchOptions {
  readonly method?: string;
  readonly params?: QueryParamsRecord;
  readonly headers?: HeadersInit;
  readonly signal?: AbortSignal;
  readonly body?: unknown;
}

export type DashboardRequestConfig = Omit<DashboardFetchOptions, 'method' | 'body'>;

export interface UcpApiClientPort {
  readonly httpClient: HttpClientPort;
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

function toHttpOptions(options?: DashboardRequestConfig): HttpRequestOptions | undefined {
  if (!options) {
    return undefined;
  }
  return {
    params: options.params,
    headers: options.headers,
    signal: options.signal,
  };
}

function normalizeRequestBody(rawBody: unknown): unknown {
  if (typeof rawBody !== 'string') {
    return rawBody;
  }
  try {
    return JSON.parse(rawBody);
  } catch {
    return rawBody;
  }
}

export interface CreateScopedUcpApiClientOptions {
  readonly getToken: () => string | null | undefined;
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createScopedUcpApiClient(
  options: CreateScopedUcpApiClientOptions,
): UcpApiClientPort {
  const logger = new StructuredJsonLoggerAdapter({
    bindings: { product: 'ucp-dashboard' },
  });

  const adapter = new FetchHttpClientAdapter({
    baseUrl: options.baseUrl ?? getApiUrl('/api/v1'),
    getToken: options.getToken,
    logger,
    fetchImpl: options.fetchImpl,
  });

  return {
    httpClient: adapter,

    async request<T>(endpoint: string, reqOptions: DashboardFetchOptions = {}): Promise<T> {
      const method = parseHttpMethod(reqOptions.method);
      const parsedBody = normalizeRequestBody(reqOptions.body);
      return unwrapOrThrow(
        await adapter.request<T>(method, endpoint, parsedBody, toHttpOptions(reqOptions)),
      );
    },

    async get<T>(endpoint: string, reqOptions?: DashboardRequestConfig): Promise<T> {
      return unwrapOrThrow(await adapter.get<T>(endpoint, toHttpOptions(reqOptions)));
    },

    async post<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return unwrapOrThrow(await adapter.post<T>(endpoint, body, toHttpOptions(reqOptions)));
    },

    async put<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return unwrapOrThrow(await adapter.put<T>(endpoint, body, toHttpOptions(reqOptions)));
    },

    async patch<T>(
      endpoint: string,
      body?: unknown,
      reqOptions?: DashboardRequestConfig,
    ): Promise<T> {
      return unwrapOrThrow(await adapter.patch<T>(endpoint, body, toHttpOptions(reqOptions)));
    },

    async delete<T>(endpoint: string, reqOptions?: DashboardRequestConfig): Promise<T> {
      return unwrapOrThrow(await adapter.delete<T>(endpoint, toHttpOptions(reqOptions)));
    },
  };
}
