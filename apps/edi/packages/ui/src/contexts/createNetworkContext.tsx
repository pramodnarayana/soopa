import {
  FetchHttpClientAdapter,
  type HttpRequestOptions,
  type QueryParamsRecord,
  StructuredJsonLoggerAdapter,
  unwrapOrThrow,
} from '@soopa/ui';
import React, { createContext, useContext, useMemo } from 'react';

export interface EdiNetworkRequestConfig {
  readonly params?: QueryParamsRecord;
  readonly headers?: HeadersInit;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

export interface EdiNetworkApi {
  readonly get: <T = unknown>(
    url: string,
    config?: EdiNetworkRequestConfig,
  ) => Promise<{ data: T }>;
  readonly post: <T = unknown>(
    url: string,
    data?: unknown,
    config?: EdiNetworkRequestConfig,
  ) => Promise<{ data: T }>;
  readonly put: <T = unknown>(
    url: string,
    data?: unknown,
    config?: EdiNetworkRequestConfig,
  ) => Promise<{ data: T }>;
  readonly patch: <T = unknown>(
    url: string,
    data?: unknown,
    config?: EdiNetworkRequestConfig,
  ) => Promise<{ data: T }>;
  readonly delete: <T = unknown>(
    url: string,
    config?: EdiNetworkRequestConfig,
  ) => Promise<{ data: T }>;
}

function toHttpOptions(config?: EdiNetworkRequestConfig): HttpRequestOptions | undefined {
  if (!config) {
    return undefined;
  }
  return {
    params: config.params,
    headers: config.headers,
    signal: config.signal,
    timeoutMs: config.timeoutMs,
  };
}

/**
 * EDI network context backed directly by the centralized @soopa/ui FetchHttpClientAdapter
 * (eliminating duplicate fetch/AbortController plumbing while preserving EDI's { data: T } adapter shape).
 */
export function createNetworkContext(hookName: string) {
  const NetworkContext = createContext<EdiNetworkApi | null>(null);

  function Provider({
    children,
    baseUrl,
    token,
    tenantId,
  }: {
    children: React.ReactNode;
    baseUrl: string;
    token?: string;
    tenantId?: string;
  }) {
    const api = useMemo<EdiNetworkApi>(() => {
      const client = new FetchHttpClientAdapter({
        baseUrl,
        getToken: () => token,
        logger: new StructuredJsonLoggerAdapter({
          bindings: { product: 'edi', context: hookName },
        }),
      });

      const resolveHttpOptions = (
        config?: EdiNetworkRequestConfig,
      ): HttpRequestOptions | undefined => {
        const baseOptions = toHttpOptions(config);
        if (!tenantId) {
          return baseOptions;
        }
        return {
          ...baseOptions,
          headers: {
            'x-tenant-id': tenantId,
            ...config?.headers,
          },
        };
      };

      return {
        get: async <T = unknown>(url: string, config?: EdiNetworkRequestConfig) => ({
          data: unwrapOrThrow(await client.get<T>(url, resolveHttpOptions(config))),
        }),
        post: async <T = unknown>(
          url: string,
          data?: unknown,
          config?: EdiNetworkRequestConfig,
        ) => ({
          data: unwrapOrThrow(await client.post<T>(url, data, resolveHttpOptions(config))),
        }),
        put: async <T = unknown>(
          url: string,
          data?: unknown,
          config?: EdiNetworkRequestConfig,
        ) => ({
          data: unwrapOrThrow(await client.put<T>(url, data, resolveHttpOptions(config))),
        }),
        patch: async <T = unknown>(
          url: string,
          data?: unknown,
          config?: EdiNetworkRequestConfig,
        ) => ({
          data: unwrapOrThrow(await client.patch<T>(url, data, resolveHttpOptions(config))),
        }),
        delete: async <T = unknown>(url: string, config?: EdiNetworkRequestConfig) => ({
          data: unwrapOrThrow(await client.delete<T>(url, resolveHttpOptions(config))),
        }),
      };
    }, [baseUrl, token, tenantId]);

    return <NetworkContext.Provider value={api}>{children}</NetworkContext.Provider>;
  }

  function useNetwork(): EdiNetworkApi {
    const context = useContext(NetworkContext);
    if (!context) {
      throw new Error(`${hookName} must be used within its Provider`);
    }
    return context;
  }

  return { Provider, useNetwork };
}
