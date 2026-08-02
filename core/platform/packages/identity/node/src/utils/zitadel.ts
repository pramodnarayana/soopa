/**
 * Extracts the org (tenant) ID from Zitadel's project roles claims.
 *
 * Zitadel encodes roles as:
 *   "urn:zitadel:iam:org:project:<id>:roles": { "<roleName>": { "<orgId>": "<domain>" } }
 *
 * When users authenticate via the global endpoint instead of an org-specific one,
 * urn:zitadel:iam:org:id is absent. The org ID is still available as a key inside
 * each role's organization map.
 */
export function extractZitadelOrgIdFromRoles(payload: Record<string, unknown>): string | undefined {
  const rolesClaims = Object.keys(payload).filter(
    (k) => k.startsWith('urn:zitadel:iam:org:project:') && k.endsWith(':roles'),
  );

  for (const claim of rolesClaims) {
    const roles = payload[claim] as Record<string, Record<string, string>> | undefined;
    if (!roles || typeof roles !== 'object') continue;

    for (const orgMap of Object.values(roles)) {
      if (!orgMap || typeof orgMap !== 'object') continue;
      const orgIds = Object.keys(orgMap);
      // Reject ambiguous claims with multiple organizations
      if (orgIds.length > 1) return undefined;
      if (orgIds.length === 1) return orgIds[0];
    }
  }

  return undefined;
}

/**
 * Resolves the Zitadel Organization (Tenant) ID from a verified JWT payload.
 *
 * Priority order:
 * 1. Direct 'urn:zitadel:iam:org:id' claim (org-scoped login)
 * 2. Extracted from project roles map keys (global-scoped login)
 */
export function resolveZitadelOrgId(payload: Record<string, unknown>): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined;

  const directOrgId = payload['urn:zitadel:iam:org:id'] as string | undefined;
  if (directOrgId) return directOrgId;

  return extractZitadelOrgIdFromRoles(payload);
}
