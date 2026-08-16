import React, { createContext, useContext, useMemo } from 'react';

type CustomRequestInit = RequestInit & { params?: Record<string, any> };
type FetchFunction = (url: string, init?: CustomRequestInit) => Promise<Response>;

export function createNetworkContext(hookName: string) {
  interface NetworkContextType {
    api: {
      get: <T = any>(url: string, config?: CustomRequestInit) => Promise<{ data: T }>;
      post: <T = any>(url: string, data?: any, config?: CustomRequestInit) => Promise<{ data: T }>;
      patch: <T = any>(url: string, data?: any, config?: CustomRequestInit) => Promise<{ data: T }>;
      delete: <T = any>(url: string, config?: CustomRequestInit) => Promise<{ data: T }>;
    };
  }

  const NetworkContext = createContext<NetworkContextType | null>(null);

  function Provider({
    children,
    baseUrl,
    token,
  }: {
    children: React.ReactNode;
    baseUrl: string;
    token?: string;
  }) {
    const api = useMemo(() => {
      const baseFetch: FetchFunction = async (url, init = {}) => {
        const headers = new Headers(init.headers);
        if (token && !headers.has('Authorization')) {
          headers.set('Authorization', `Bearer ${token}`);
        }
        if (!headers.has('Content-Type') && init.method !== 'GET' && init.method !== 'HEAD') {
          headers.set('Content-Type', 'application/json');
        }

        let fullUrl = `${baseUrl}${url}`;
        if (init.params) {
          const searchParams = new URLSearchParams();
          for (const [key, value] of Object.entries(init.params)) {
            if (value !== undefined && value !== null) {
              searchParams.append(key, String(value));
            }
          }
          const queryString = searchParams.toString();
          if (queryString) {
            fullUrl += (fullUrl.includes('?') ? '&' : '?') + queryString;
          }
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 15000);

        // Combine caller-provided signal with timeout signal
        let combinedSignal = controller.signal;
        if (init.signal) {
          const callerSignal = init.signal;
          // Browser-compatible signal combination: listen to both signals
          const abortHandler = () => controller.abort();
          callerSignal.addEventListener('abort', abortHandler, { once: true });
          // Clean up listener if timeout fires first
          controller.signal.addEventListener('abort', () => {
            callerSignal.removeEventListener('abort', abortHandler);
          }, { once: true });
        }

        try {
          const response = await fetch(fullUrl, { ...init, headers, signal: combinedSignal });

          if (!response.ok) {
            let message = response.statusText;
            try {
              const err = await response.json();
              message = err.message || err.detail || message;
            } catch {
              // ignore
            }
            throw new Error(message);
          }
          return response;
        } finally {
          clearTimeout(timeoutId);
        }
      };

      return {
        get: async <T = any>(url: string, config?: CustomRequestInit) => {
          const res = await baseFetch(url, { ...config, method: 'GET' });
          if (res.status === 204) return { data: undefined as unknown as T };
          return { data: (await res.json()) as T };
        },
        post: async <T = any>(url: string, data?: any, config?: CustomRequestInit) => {
          const res = await baseFetch(url, {
            ...config,
            method: 'POST',
            body: data !== undefined ? JSON.stringify(data) : undefined,
          });
          if (res.status === 204) return { data: undefined as unknown as T };
          return { data: (await res.json()) as T };
        },
        patch: async <T = any>(url: string, data?: any, config?: CustomRequestInit) => {
          const res = await baseFetch(url, {
            ...config,
            method: 'PATCH',
            body: data !== undefined ? JSON.stringify(data) : undefined,
          });
          if (res.status === 204) return { data: undefined as unknown as T };
          return { data: (await res.json()) as T };
        },
        delete: async <T = any>(url: string, config?: CustomRequestInit) => {
          const res = await baseFetch(url, { ...config, method: 'DELETE' });
          if (res.status === 204) return { data: undefined as unknown as T };
          return { data: (await res.json()) as T };
        },
      };
    }, [baseUrl, token]);

    return <NetworkContext.Provider value={{ api }}>{children}</NetworkContext.Provider>;
  }

  function useNetwork() {
    const context = useContext(NetworkContext);
    if (!context) {
      throw new Error(`${hookName} must be used within its Provider`);
    }
    return context.api;
  }

  return { Provider, useNetwork };
}
