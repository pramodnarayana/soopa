import * as crypto from 'crypto';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { IdentityInfrastructureError } from '../../../domain/Errors.js';
import type { TokenClaims } from '../../../domain/IdentityContext.js';
import type { TokenVerifier } from '../../../ports/TokenVerifier.js';

export interface ZitadelTokenVerifierOptions {
  issuer: string;
  audience: string;
  jwksUrl?: string;
  userinfoUrl?: string;
}

interface CachedUserinfo {
  data: Record<string, unknown>;
  expiry: number;
}

export class ZitadelJwksVerifier implements TokenVerifier {
  private readonly jwks: ReturnType<typeof createRemoteJWKSet>;
  private userinfoCache: Map<string, CachedUserinfo> = new Map();
  private readonly USERINFO_TTL_MS = 3600000; // 1 hour
  private readonly MAX_CACHE_SIZE = 1000;

  constructor(private readonly options: ZitadelTokenVerifierOptions) {
    const jwksUrl = options.jwksUrl ?? `${options.issuer}/oauth/v2/keys`;
    this.jwks = createRemoteJWKSet(new URL(jwksUrl));
  }

  private evictIfNeeded() {
    if (this.userinfoCache.size > this.MAX_CACHE_SIZE) {
      const now = Date.now();
      for (const [key, value] of this.userinfoCache.entries()) {
        if (now >= value.expiry) {
          this.userinfoCache.delete(key);
        }
      }
      // If still over limit after expiry-based eviction, delete oldest entries
      if (this.userinfoCache.size > this.MAX_CACHE_SIZE) {
        const entriesToDelete = this.userinfoCache.size - this.MAX_CACHE_SIZE;
        let deleted = 0;
        for (const key of this.userinfoCache.keys()) {
          if (deleted >= entriesToDelete) break;
          this.userinfoCache.delete(key);
          deleted++;
        }
      }
    }
  }

  async verify(token: string): Promise<TokenClaims> {
    const result = await jwtVerify(token, this.jwks, {
      audience: this.options.audience,
      issuer: this.options.issuer,
    });

    const claims = result.payload as Record<string, unknown>;

    if (typeof claims.sub !== 'string') {
      throw new IdentityInfrastructureError('Token is missing required sub claim.');
    }

    // OIDC Opaque Token Scopes: If Zitadel custom roles are missing from the access token, fetch from userinfo endpoint
    if (
      !claims['urn:zitadel:iam:org:project:roles'] &&
      !claims[`urn:zitadel:iam:org:project:id:${this.options.audience}:roles`]
    ) {
      const cacheKey =
        (claims.jti as string | undefined) ??
        crypto.createHash('sha256').update(token).digest('hex');
      let cachedData: Record<string, unknown> | null = null;

      const cached = this.userinfoCache.get(cacheKey);
      if (cached && Date.now() < cached.expiry) {
        cachedData = cached.data;
      }

      if (cachedData) {
        Object.assign(claims, cachedData);
      } else {
        const userinfoUrl = this.options.userinfoUrl ?? `${this.options.issuer}/oidc/v1/userinfo`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        try {
          const response = await fetch(userinfoUrl, {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          });

          if (response.ok) {
            const userinfo = (await response.json()) as Record<string, unknown>;
            Object.assign(claims, userinfo);
            const tokenExpMs = typeof claims.exp === 'number' ? claims.exp * 1000 : Infinity;
            this.userinfoCache.set(cacheKey, {
              data: userinfo,
              expiry: Math.min(Date.now() + this.USERINFO_TTL_MS, tokenExpMs),
            });
            this.evictIfNeeded();
          } else if (response.status >= 400 && response.status < 500) {
            // 4xx client errors (401, 403, etc.) indicate authentication/authorization failures
            // Skip userinfo enrichment and proceed with base token claims
            // This allows the verification to complete with available claims
          } else {
            // 5xx server errors are infrastructure issues
            throw new IdentityInfrastructureError(
              `Failed to fetch userinfo from Zitadel: HTTP ${response.status}`,
            );
          }
        } catch (e: unknown) {
          if (e instanceof Error && e.name === 'AbortError') {
            throw new IdentityInfrastructureError('Userinfo request timed out after 5 seconds');
          } else if (e instanceof IdentityInfrastructureError) {
            throw e;
          } else {
            throw new IdentityInfrastructureError(
              `Failed to fetch userinfo: ${e instanceof Error ? e.message : String(e)}`,
            );
          }
        } finally {
          clearTimeout(timeoutId);
        }
      }
    }

    const mappedClaims: TokenClaims = {
      ...claims, // Spread all custom claims first
      // Explicit mappings take precedence
      sub: claims.sub,
      email: claims.email as string | undefined,
      preferred_username: claims.preferred_username as string | undefined,
      name: claims.name as string | undefined,
      idpTenantId: (claims['urn:zitadel:iam:org:id'] || claims.tenant_id) as string | undefined,
      tenant_id: claims.tenant_id as string | undefined,
    };

    return mappedClaims;
  }
}
