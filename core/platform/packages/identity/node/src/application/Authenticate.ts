import {
  MissingIdentityTenantError,
  MissingUserDomainError,
  TenantMappingDomainError,
} from '../domain/Errors.js';
import type { IdentityContext } from '../domain/IdentityContext.js';
import type { TenantRepository } from '../ports/TenantRepository.js';
import type { TokenVerifier } from '../ports/TokenVerifier.js';
import { resolveZitadelOrgId } from '../utils/zitadel.js';

export interface AuthenticateOptions {
  audience: string;
}

export class AuthenticateUseCase {
  constructor(
    private readonly tokenVerifier: TokenVerifier,
    private readonly tenantRepo: TenantRepository,
    private readonly options: AuthenticateOptions,
  ) {}

  async execute(token: string): Promise<IdentityContext> {
    // 1. Cryptographically verify JWT via JWKS
    const claims = await this.tokenVerifier.verify(token);

    const email = claims.email || claims.preferred_username || claims.sub;
    // Resolve the external Identity Provider Org ID from Zitadel claims
    const idpTenantId: string | undefined = resolveZitadelOrgId(claims) || claims.tenant_id;

    console.log(
      `[AUTH DEBUG] claims.email: ${claims.email}, claims.preferred_username: ${claims.preferred_username}, claims.sub: ${claims.sub}`,
    );
    console.log(`[AUTH DEBUG] Resolved email: ${email}, idpTenantId: ${idpTenantId}`);

    if (!idpTenantId) {
      throw new MissingIdentityTenantError(email);
    }

    // Determine PlatformAdmin role
    const defaultRoles = claims['urn:zitadel:iam:org:project:roles'] as
      | Record<string, unknown>
      | undefined;
    const ucpRoles = claims[`urn:zitadel:iam:org:project:id:${this.options.audience}:roles`] as
      | Record<string, unknown>
      | undefined;
    const isPlatformAdmin = !!(
      (defaultRoles && 'PlatformAdmin' in defaultRoles) ||
      (ucpRoles && 'PlatformAdmin' in ucpRoles)
    );

    const roles: string[] = [];
    const rawRoles: string[] = [];
    if (defaultRoles) {
      Object.keys(defaultRoles).forEach((r) => rawRoles.push(r));
    }
    if (ucpRoles) {
      Object.keys(ucpRoles).forEach((r) => rawRoles.push(r));
    }
    if (isPlatformAdmin) {
      roles.push('PlatformAdmin');
    }

    // 2. Strict User Resolution — No JIT Provisioning.
    //    Users MUST be synced via the Zitadel Webhook before they can log in.
    const idpUserId = claims.sub;
    const user = await this.tenantRepo.findUserByIdpId(idpUserId);

    if (!user) {
      throw new MissingUserDomainError(idpUserId);
    }

    const tenantId = (await this.tenantRepo.getTenantMappingForUser(user.id)) ?? '';

    if (!tenantId && !isPlatformAdmin) {
      throw new TenantMappingDomainError(email);
    }

    // 3. Return IdentityContext
    return {
      userId: user.id,
      tenantId,
      email,
      name: user.name,
      roles,
      rawRoles,
      isPlatformAdmin,
    };
  }
}
