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
      if (this.userinfoCache.size > this.MAX_CACHE_SIZE) {
        this.userinfoCache.clear();
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
      const jti = claims.jti as string | undefined;
      let cachedData: Record<string, unknown> | null = null;
      
      if (jti) {
        const cached = this.userinfoCache.get(jti);
        if (cached && Date.now() < cached.expiry) {
          cachedData = cached.data;
        }
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
            if (jti) {
              this.userinfoCache.set(jti, {
                data: userinfo,
                expiry: Date.now() + this.USERINFO_TTL_MS,
              });
              this.evictIfNeeded();
            }
          } else {
            console.error('[ZitadelJwksVerifier] Failed to fetch userinfo, status:', response.status);
          }
        } catch (e: unknown) {
          if (e instanceof Error && e.name === 'AbortError') {
            console.error('[ZitadelJwksVerifier] Userinfo request timed out after 5 seconds');
          } else {
            console.error('[ZitadelJwksVerifier] Failed to fetch userinfo request', e);
          }
        } finally {
          clearTimeout(timeoutId);
        }
      }
    }

    const mappedClaims: TokenClaims = {
      sub: claims.sub,
      email: claims.email as string | undefined,
      preferred_username: claims.preferred_username as string | undefined,
      name: claims.name as string | undefined,
      idpTenantId: (claims['urn:zitadel:iam:org:id'] || claims.tenant_id) as string | undefined,
      tenant_id: claims.tenant_id as string | undefined,
      ...claims, // Spread all custom claims like roles for downstream UseCases
    };

    return mappedClaims;
  }
}
