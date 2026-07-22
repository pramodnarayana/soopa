import type { TokenVerifier } from '../ports/TokenVerifier.js';
import type { IdentityContext } from '../domain/IdentityContext.js';
import type { TenantRepository } from '../ports/TenantRepository.js';
import { TenantMappingDomainError } from '../domain/Errors.js';

export class AuthenticateUseCase {
  constructor(
    private readonly tokenVerifier: TokenVerifier,
    private readonly tenantRepo: TenantRepository
  ) {}

  async execute(token: string): Promise<IdentityContext> {
    // 1. Cryptographically verify JWT via JWKS
    const claims = await this.tokenVerifier.verify(token);
    
    const email = claims.email || claims.preferred_username || claims.sub;
    const name = claims.name || email.split('@')[0];
    const zitadelOrgId = claims['urn:zitadel:iam:org:id'] || claims.tenant_id;

    // 2. JIT Provisioning & DB Sync via pure Port
    const user = await this.tenantRepo.findUserByEmail(email);

    if (!user) {
      const provisioned = await this.tenantRepo.provisionUserAndTenant(email, name, zitadelOrgId);
      return {
        userId: provisioned.userId,
        tenantId: provisioned.tenantId,
        email,
        name,
        roles: ['admin'] // In a real app, parse this from Zitadel roles or local tenantUsers table
      };
    }

    const tenantId = await this.tenantRepo.getTenantMappingForUser(user.id) ?? '';
    
    if (!tenantId) {
      throw new TenantMappingDomainError(email);
    }

    // 3. Return generic IdentityContext
    return {
      userId: user.id,
      tenantId,
      email,
      name: user.name,
      roles: ['admin']
    };
  }
}
