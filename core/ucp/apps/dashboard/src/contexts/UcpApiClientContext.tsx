import React, { createContext, useContext, useLayoutEffect, useMemo, useRef } from 'react';
import { createScopedUcpApiClient, type UcpApiClientPort } from '../lib/api-client';

const UcpApiClientContext = createContext<UcpApiClientPort | null>(null);

export interface UcpApiClientProviderProps {
  readonly token: string | null;
  readonly clientOverride?: UcpApiClientPort;
  readonly children: React.ReactNode;
}

export function UcpApiClientProvider({
  token,
  clientOverride,
  children,
}: UcpApiClientProviderProps) {
  const tokenRef = useRef<string | null>(token);
  useLayoutEffect(() => {
    tokenRef.current = token;
  }, [token]);

  const client = useMemo<UcpApiClientPort>(
    () =>
      clientOverride ??
      createScopedUcpApiClient({
        getToken: () => tokenRef.current,
      }),
    [clientOverride],
  );

  return <UcpApiClientContext.Provider value={client}>{children}</UcpApiClientContext.Provider>;
}

export function useUcpApiClient(): UcpApiClientPort {
  const client = useContext(UcpApiClientContext);
  if (!client) {
    throw new Error('useUcpApiClient must be used inside <UcpApiClientProvider>.');
  }
  return client;
}
