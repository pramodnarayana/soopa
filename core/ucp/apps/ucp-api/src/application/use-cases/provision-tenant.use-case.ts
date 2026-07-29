import { Inject, Injectable } from '@nestjs/common';
import { IsNotEmpty, IsString } from 'class-validator';
import * as crypto from 'crypto';
import { Tenant } from '../../domain/models/tenant.model.js';
import type { IOrganizationProvider } from '../../ports/outbound/organization.provider.js';
import { ORGANIZATION_PROVIDER } from '../../ports/outbound/organization.provider.js';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';
import type { IUserIdentityProvider } from '../../ports/outbound/user-identity.provider.js';
import { USER_IDENTITY_PROVIDER } from '../../ports/outbound/user-identity.provider.js';

export class ProvisionTenantDto {
  @IsString()
  @IsNotEmpty()
  name!: string;
}

@Injectable()
export class ProvisionTenantUseCase {
  constructor(
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(ORGANIZATION_PROVIDER)
    private readonly organizationProvider: IOrganizationProvider,
    @Inject(USER_IDENTITY_PROVIDER)
    private readonly userIdentityProvider: IUserIdentityProvider,
  ) {}

  async execute(dto: ProvisionTenantDto): Promise<Tenant> {
    // 1. Call Zitadel to create an Organization
    const { orgId } = await this.organizationProvider.createOrganization(dto.name);

    // 2. Generate a local ID for the tenant
    const localId = `ten_${crypto.randomBytes(8).toString('hex')}`;

    // 3. Create Tenant Domain Entity
    const tenant = Tenant.create(localId, dto.name, orgId, null, []);

    // 4. Save to DB (Repository handles Transaction and Outbox automatically)
    await this.tenantRepo.save(tenant);

    return tenant;
  }
}
