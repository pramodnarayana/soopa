import { MissingIdentityTenantError, TenantMappingDomainError } from '../domain/Errors.js';
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
    // 1. Cryptographically verify JWT via JWKS (and fetch userinfo if necessary)
    const claims = await this.tokenVerifier.verify(token);

    const email = claims.email || claims.preferred_username || claims.sub;
    const name = claims.name || email.split('@')[0];

    // Use the robust utility to resolve the external Identity Provider ID
    const idpTenantId: string | undefined = resolveZitadelOrgId(claims) || claims.tenant_id;

    if (!idpTenantId) {
      throw new MissingIdentityTenantError(email);
    }

    // Determine PlatformAdmin role
    const defaultRoles = claims['urn:zitadel:iam:org:project:roles'] as Record<string, unknown> | undefined;
    const ucpRoles = claims[`urn:zitadel:iam:org:project:id:${this.options.audience}:roles`] as Record<string, unknown> | undefined;
    const isPlatformAdmin = !!((defaultRoles && 'PlatformAdmin' in defaultRoles) || (ucpRoles && 'PlatformAdmin' in ucpRoles));

    // Resolve specific roles for this context
    const roles: string[] = [];
    const rawRoles: string[] = [];
    if (defaultRoles) {
      Object.keys(defaultRoles).forEach(r => rawRoles.push(r));
    }
    if (ucpRoles) {
      Object.keys(ucpRoles).forEach(r => rawRoles.push(r));
    }
    if (isPlatformAdmin) {
      roles.push('PlatformAdmin');
    }

    // 2. JIT Provisioning & DB Sync via pure Port
    const user = await this.tenantRepo.findUserByEmail(email);

    if (!user) {
      const provisioned = await this.tenantRepo.provisionUserAndTenant(email, name, idpTenantId);
      return {
        userId: provisioned.userId,
        tenantId: provisioned.tenantId,
        email,
        name,
        roles,
        rawRoles,
        isPlatformAdmin,
      };
    }

    const tenantId = (await this.tenantRepo.getTenantMappingForUser(user.id)) ?? '';

    if (!tenantId && !isPlatformAdmin) {
      throw new TenantMappingDomainError(email);
    }

    // 3. Return generic IdentityContext
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
