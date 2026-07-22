import type { TokenClaims } from '../domain/IdentityContext.js';

export interface TokenVerifier {
  verify(token: string): Promise<TokenClaims>;
}
