import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import type { IOrganizationProvider } from '../../ports/outbound/organization.provider.js';
import { ORGANIZATION_PROVIDER } from '../../ports/outbound/organization.provider.js';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';
import type { IUserRepository } from '../../ports/outbound/user.repository.js';
import { USER_REPOSITORY } from '../../ports/outbound/user.repository.js';

@Injectable()
export class DeleteTenantUseCase {
  private readonly logger = new Logger(DeleteTenantUseCase.name);

  constructor(
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(USER_REPOSITORY) private readonly userRepo: IUserRepository,
    @Inject(ORGANIZATION_PROVIDER)
    private readonly organizationProvider: IOrganizationProvider,
  ) {}

  async execute(tenantId: string): Promise<void> {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    // 1. Fetch users belonging to this tenant before deletion
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const userIds = tenantUsers.map((u) => u.id);

    // 2. Delete tenant and all its strictly dependent infrastructure resources
    // (api_keys, shards, outbox events, and the tenant_users bridge records)
    await this.tenantRepo.delete(tenantId);

    // 3. Delete any users that no longer belong to any active tenants
    if (userIds.length > 0) {
      await this.userRepo.deleteOrphanedUsers(userIds);
    }

    // 4. Clean up Zitadel Organization (best effort)
    if (tenant.idpTenantId) {
      try {
        await this.organizationProvider.deleteOrganization(tenant.idpTenantId);
      } catch (err) {
        this.logger.error(
          `Warning: Failed to delete organization ${tenant.idpTenantId} from Zitadel`,
          err,
        );
      }
    }
  }
}
