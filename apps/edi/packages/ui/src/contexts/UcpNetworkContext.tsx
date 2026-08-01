import axios, { type AxiosInstance } from 'axios';
import React, { createContext, useContext, useMemo } from 'react';

interface UcpNetworkContextType {
  api: AxiosInstance;
}

const UcpNetworkContext = createContext<UcpNetworkContextType | null>(null);

export function UcpNetworkProvider({
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

  return <UcpNetworkContext.Provider value={{ api }}>{children}</UcpNetworkContext.Provider>;
}

export function useUcpNetwork() {
  const context = useContext(UcpNetworkContext);
  if (!context) {
    throw new Error('useUcpNetwork must be used within an UcpNetworkProvider');
  }
  return context.api;
}
