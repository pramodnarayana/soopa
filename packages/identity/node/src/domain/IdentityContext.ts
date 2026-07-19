export interface TokenClaims {
  sub: string;
  email?: string;
  preferred_username?: string;
  name?: string;
  // Zitadel Organization ID (if present)
  'urn:zitadel:iam:org:id'?: string;
  // Fallback for custom tenant implementations
  tenant_id?: string;
}

export interface IdentityContext {
  userId: string;
  tenantId: string;
  email: string;
  name: string;
  roles: string[];
}
