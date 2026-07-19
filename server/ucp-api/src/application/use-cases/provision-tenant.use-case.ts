import { Injectable, Inject } from '@nestjs/common';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository';
import type { IIdentityProvider } from '../../ports/outbound/identity.provider';
import { IDENTITY_PROVIDER } from '../../ports/outbound/identity.provider';
import { Tenant } from '../../domain/models/tenant.model';
import * as crypto from 'crypto';

export class ProvisionTenantDto {
  name: string;
  appSlugs: string[];
  adminEmail: string;
}

@Injectable()
export class ProvisionTenantUseCase {
  constructor(
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(IDENTITY_PROVIDER)
    private readonly identityProvider: IIdentityProvider,
  ) {}

  async execute(dto: ProvisionTenantDto): Promise<Tenant> {
    // 1. Call Zitadel to create an Organization
    const { orgId } = await this.identityProvider.createOrganization(dto.name);

    // 2. Generate a local ID for the tenant
    const localId = `ten_${crypto.randomBytes(8).toString('hex')}`;

    // 3. Create Tenant Domain Entity (adds Domain Event internally)
    const tenant = Tenant.create(localId, dto.name, orgId, dto.appSlugs);

    // 4. Save to DB (Repository handles Transaction and Outbox automatically)
    await this.tenantRepo.save(tenant);

    // 5. Create User in Zitadel
    // await this.identityProvider.inviteUser(orgId, dto.adminEmail);

    return tenant;
  }
}
