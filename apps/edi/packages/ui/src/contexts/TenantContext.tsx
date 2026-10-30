import { TenantSessionProvider, useOptionalTenantId } from '@soopa/ui';
import React from 'react';

export function TenantProvider({
  tenantId,
  children,
}: {
  tenantId?: string;
  children: React.ReactNode;
}) {
  return <TenantSessionProvider tenantId={tenantId}>{children}</TenantSessionProvider>;
}

export function useTenantId(): string {
  return useOptionalTenantId();
}
