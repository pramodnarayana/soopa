export interface TokenClaims {
  sub: string;
  email?: string;
  preferred_username?: string;
  name?: string;
  // Identity Provider's Tenant/Org ID
  idpTenantId?: string;
  // Fallback for custom tenant implementations
  tenant_id?: string;
  [key: string]: unknown;
}

export interface IdentityContext {
  userId: string;
  tenantId: string;
  email: string;
  name: string;
  roles: string[];
  rawRoles: string[];
  isPlatformAdmin: boolean;
}
