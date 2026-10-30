import React, { createContext, useContext, useMemo } from 'react';

export interface TenantSessionValue {
  readonly tenantId: string;
  readonly token: string;
}

export const TenantSessionContext = createContext<TenantSessionValue | null>(null);

export interface TenantSessionProviderProps {
  readonly tenantId?: string;
  readonly token?: string;
  readonly children: React.ReactNode;
}

export function TenantSessionProvider({
  tenantId = '',
  token = '',
  children,
}: TenantSessionProviderProps) {
  const value = useMemo<TenantSessionValue>(() => ({ tenantId, token }), [tenantId, token]);
  return <TenantSessionContext.Provider value={value}>{children}</TenantSessionContext.Provider>;
}

export function useTenantSession(): TenantSessionValue {
  const ctx = useContext(TenantSessionContext);
  if (!ctx || !ctx.tenantId) {
    throw new Error(
      'useTenantSession must be used inside a <TenantSessionProvider> with a resolved tenantId.',
    );
  }
  return ctx;
}

export function useOptionalTenantId(): string {
  const ctx = useContext(TenantSessionContext);
  return ctx?.tenantId ?? '';
}
