const UCP_API_URL = import.meta.env.VITE_UCP_API_URL || 'http://localhost:3000';

let globalToken: string | null = null;
class ApiError extends Error {
  public statusCode: number;
  public details?: any;

  constructor(message: string, statusCode: number, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.details = details;
  }
}

interface FetchOptions extends RequestInit {
  params?: Record<string, string>;
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
    if (!normalizedHeaders.has('Content-Type')) {
      normalizedHeaders.set('Content-Type', 'application/json');
    }
    if (globalToken && !normalizedHeaders.has('Authorization')) {
      normalizedHeaders.set('Authorization', `Bearer ${globalToken}`);
    }

    const config: RequestInit = {
      ...customConfig,
      headers: normalizedHeaders,
    };

    const response = await fetch(url.toString(), config);

    if (!response.ok) {
      let errorMessage = 'An unexpected error occurred';
      let errorDetails: any = null;

      const textData = await response.text();

      if (textData) {
        try {
          const errorData = JSON.parse(textData);
          errorMessage = errorData.message || errorMessage;
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
      return await response.json();
    } catch {
      return {} as T;
    }
  },

  get<T>(endpoint: string, options?: Omit<FetchOptions, 'method'>) {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  },

  post<T>(endpoint: string, body?: any, options?: Omit<FetchOptions, 'method' | 'body'>) {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  patch<T>(endpoint: string, body?: any, options?: Omit<FetchOptions, 'method' | 'body'>) {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  delete<T>(endpoint: string, options?: Omit<FetchOptions, 'method'>) {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }
};
