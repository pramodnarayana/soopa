import React, { createContext, useContext } from 'react';

const TenantContext = createContext<string | undefined>(undefined);

export function TenantProvider({
  tenantId,
  children,
}: {
  tenantId?: string;
  children: React.ReactNode;
}) {
  return <TenantContext.Provider value={tenantId}>{children}</TenantContext.Provider>;
}

export function useTenantId() {
  const tenantId = useContext(TenantContext);
  if (!tenantId) {
    console.warn(
      'useTenantId: No tenant ID found in context. API calls requiring tenantId may fail.',
    );
  }
  return tenantId || '';
}
