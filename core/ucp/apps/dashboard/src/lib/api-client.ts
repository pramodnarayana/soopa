const UCP_API_BASE = (
  (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL || 'http://localhost:3000'
).replace(/\/+$/, '');
const UCP_API_URL = `${UCP_API_BASE}/api/v1`;

let globalToken: string | null = null;

class ApiError extends Error {
  public statusCode: number;
  public details?: unknown;

  constructor(message: string, statusCode: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.details = details;
  }
}

interface FetchOptions extends RequestInit {
  params?: Record<string, string>;
}

function getIdempotencyKey(): string {
  return crypto.randomUUID();
}

export const apiClient = {
  setToken(token: string | null) {
    globalToken = token;
  },

  async request<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
    const { params, headers, ...customConfig } = options;

    const url = new URL(`${UCP_API_URL}${endpoint}`);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.append(key, value);
      });
    }

    const normalizedHeaders = new Headers(headers);
    if (!normalizedHeaders.has('Content-Type') && customConfig.body !== undefined) {
      normalizedHeaders.set('Content-Type', 'application/json');
    }
    if (globalToken && !normalizedHeaders.has('Authorization')) {
      normalizedHeaders.set('Authorization', `Bearer ${globalToken}`);
    }

    // Inject strict idempotency key for mutating requests
    const method = customConfig.method?.toUpperCase() || 'GET';
    if (
      ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) &&
      !normalizedHeaders.has('Idempotency-Key')
    ) {
      const idempotencyKey = getIdempotencyKey();
      normalizedHeaders.set('Idempotency-Key', idempotencyKey);
    }

    const config: RequestInit = {
      ...customConfig,
      headers: normalizedHeaders,
    };

    const response = await fetch(url.toString(), config);

    if (!response.ok) {
      let errorMessage = 'An unexpected error occurred';
      let errorDetails: unknown = null;

      const textData = await response.text();

      if (textData) {
        try {
          const errorData = JSON.parse(textData) as Record<string, unknown>;
          if (typeof errorData.message === 'string') {
            errorMessage = errorData.message;
          }
          errorDetails = errorData.details || errorData;
        } catch {
          // Fallback if response is not valid JSON
          errorMessage = textData;
        }
      }

      throw new ApiError(errorMessage, response.status, errorDetails);
    }

    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return {} as T;
    }

    try {
      return (await response.json()) as T;
    } catch {
      return {} as T;
    }
  },

  get<T>(endpoint: string, options?: Omit<FetchOptions, 'method'>) {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  },

  post<T>(endpoint: string, body?: unknown, options?: Omit<FetchOptions, 'method' | 'body'>) {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  patch<T>(endpoint: string, body?: unknown, options?: Omit<FetchOptions, 'method' | 'body'>) {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  delete<T>(endpoint: string, options?: Omit<FetchOptions, 'method'>) {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  },
};
