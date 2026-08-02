/**
 * Resolves the UCP API URL from environment variables.
 * Falls back to localhost:3000 if not configured.
 */
export function getUcpApiUrl(): string {
  return (
    (import.meta.env as unknown as Record<string, string>).VITE_UCP_API_URL ||
    'http://localhost:3000'
  );
}

/**
 * Decodes a JWT payload without verifying the signature.
 * Verification is performed server-side by the UCP API.
 * Used client-side only to extract non-sensitive claims (e.g. tenant/org ID).
 */
export function parseJwtPayload(token: string): Record<string, unknown> {
  try {
    const base64url = token.split('.')[1];
    if (!base64url) return {};
    // Normalize base64url to standard Base64: replace '-' with '+', '_' with '/', and restore padding
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/').padEnd(
      base64url.length + ((4 - (base64url.length % 4)) % 4),
      '='
    );
    return JSON.parse(atob(base64)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/**
 * Resolves the tenant ID from available auth sources in priority order:
 * 1. Access token 'urn:zitadel:iam:org:id'           (org-scoped login — most reliable)
 * 2. Access token 'urn:zitadel:iam:org:project:roles' (global login — extract org ID from roles map)
 * 3. ID token profile 'idpTenantId' / 'tenant_id'    (custom claim mapper fallback)
 *
 * Zitadel encodes roles as: { "<roleName>": { "<orgId>": "<orgDomain>" } }
 * When a user authenticates via the global endpoint (not org-specific), 'urn:zitadel:iam:org:id'
 * is absent, but the org ID is still accessible as a key inside the roles map.
 */
export function resolveTenantId(
  accessToken: string | undefined,
  profile: Record<string, unknown>,
): string | undefined {
  if (accessToken) {
    const payload = parseJwtPayload(accessToken);

    // Priority 1: direct org ID claim (org-scoped login)
    const orgId = payload['urn:zitadel:iam:org:id'] as string | undefined;
    if (orgId) return orgId;

    // Priority 2: extract org ID from project roles claim (global login)
    const orgIdFromRoles = extractOrgIdFromRoles(payload);
    if (orgIdFromRoles) return orgIdFromRoles;
  }

  // Priority 3: custom claim mapper / legacy fields in ID token
  return (
    (profile['idpTenantId'] as string | undefined) ||
    (profile['tenant_id'] as string | undefined) ||
    undefined
  );
}

/**
 * Zitadel roles claims have the structure:
 *   { "<roleName>": { "<orgId>": "<primaryDomain>" } }
 *
 * We look at both the project-scoped and global project roles claims
 * and return the first org ID found.
 */
function extractOrgIdFromRoles(payload: Record<string, unknown>): string | undefined {
  const rolesClaims = [
    'urn:zitadel:iam:org:project:roles',
    ...Object.keys(payload).filter(
      (k) => k.startsWith('urn:zitadel:iam:org:project:') && k.endsWith(':roles'),
    ),
  ];

  for (const claim of rolesClaims) {
    const roles = payload[claim] as Record<string, Record<string, string>> | undefined;
    if (!roles || typeof roles !== 'object') continue;

    for (const orgMap of Object.values(roles)) {
      if (!orgMap || typeof orgMap !== 'object') continue;
      const orgId = Object.keys(orgMap)[0];
      if (orgId) return orgId;
    }
  }

  return undefined;
}
