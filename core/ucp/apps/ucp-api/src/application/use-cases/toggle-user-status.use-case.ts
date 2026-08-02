import { BadRequestException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';
import type { IUserRepository } from '../../ports/outbound/user.repository.js';
import { USER_REPOSITORY } from '../../ports/outbound/user.repository.js';
import type { IUserIdentityProvider } from '../../ports/outbound/user-identity.provider.js';
import { USER_IDENTITY_PROVIDER } from '../../ports/outbound/user-identity.provider.js';

@Injectable()
export class ToggleUserStatusUseCase {
  constructor(
    @Inject(USER_REPOSITORY) private readonly userRepo: IUserRepository,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(USER_IDENTITY_PROVIDER) private readonly userIdentityProvider: IUserIdentityProvider,
  ) {}

  async execute(
    tenantId: string,
    userId: string,
    action: 'activate' | 'deactivate',
  ): Promise<void> {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.idpTenantId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    // Verify user belongs to this tenant
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const tenantUser = tenantUsers.find((u: { id: string }) => u.id === userId);
    if (!tenantUser || !tenantUser.idpUserId) {
      throw new NotFoundException('User identity mapping not found in this tenant');
    }

    // Load rich aggregate root
    const user = await this.userRepo.findById(userId);
    if (!user || !user.idpUserId) {
      throw new NotFoundException('User domain entity not found');
    }

    // 1. Sync external state first (Outbound Port)
    await this.userIdentityProvider.toggleUserStatus(user.idpUserId, tenant.idpTenantId, action);

    // 2. Perform business logic on the rich Domain Model
    if (action === 'activate') {
      user.activate();
    } else {
      user.deactivate();
    }

    // 3. Persist local state
    await this.userRepo.save(user);
  }
}
