import { createContext, useContext } from 'react';

export interface TenantContextValue {
  tenantId: string;
  token: string;
}

export const TenantContext = createContext<TenantContextValue | null>(null);

/**
 * Returns the resolved tenantId and access token for the current tenant session.
 * Guaranteed non-null — the parent TenantLayout throws a FATAL error if tenantId is missing.
 */
export function useTenantContext(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error(
      'useTenantContext must be used inside <TenantContext.Provider>. ' +
        'Ensure this component is rendered within a tenant route.',
    );
  }
  return ctx;
}
