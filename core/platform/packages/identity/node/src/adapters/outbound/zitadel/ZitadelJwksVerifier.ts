import { createRemoteJWKSet, jwtVerify } from 'jose';
import { IdentityInfrastructureError } from '../../../domain/Errors.js';
import type { TokenClaims } from '../../../domain/IdentityContext.js';
import type { TokenVerifier } from '../../../ports/TokenVerifier.js';

export interface ZitadelTokenVerifierOptions {
  issuer: string;
  audience: string;
  jwksUrl?: string;
}

export class ZitadelJwksVerifier implements TokenVerifier {
  private readonly jwks: ReturnType<typeof createRemoteJWKSet>;

  constructor(private readonly options: ZitadelTokenVerifierOptions) {
    const jwksUrl = options.jwksUrl ?? `${options.issuer}/oauth/v2/keys`;
    this.jwks = createRemoteJWKSet(new URL(jwksUrl));
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

    return claims as unknown as TokenClaims;
  }
}
