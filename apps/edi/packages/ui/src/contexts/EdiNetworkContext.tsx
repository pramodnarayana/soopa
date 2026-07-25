import axios, { type AxiosInstance } from 'axios';
import React, { createContext, useContext, useMemo } from 'react';

interface EdiNetworkContextType {
  api: AxiosInstance;
}

const EdiNetworkContext = createContext<EdiNetworkContextType | null>(null);

export function EdiNetworkProvider({
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
    });

    if (token) {
      instance.interceptors.request.use((config) => {
        config.headers.Authorization = `Bearer ${token}`;
        return config;
      });
    }

    return instance;
  }, [baseUrl, token]);

  return <EdiNetworkContext.Provider value={{ api }}>{children}</EdiNetworkContext.Provider>;
}

export function useEdiNetwork() {
  const context = useContext(EdiNetworkContext);
  if (!context) {
    throw new Error('useEdiNetwork must be used within an EdiNetworkProvider');
  }
  return context.api;
}
