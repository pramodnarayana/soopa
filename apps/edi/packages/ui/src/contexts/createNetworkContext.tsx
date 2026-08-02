import axios, { type AxiosInstance } from 'axios';
import React, { createContext, useContext, useMemo } from 'react';

export function createNetworkContext(hookName: string) {
  interface NetworkContextType {
    api: AxiosInstance;
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
      const instance = axios.create({
        baseURL: baseUrl,
        timeout: 15000,
      });

      if (token) {
        instance.interceptors.request.use((config) => {
          config.headers.Authorization = `Bearer ${token}`;
          return config;
        });
      }

      return instance;
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
