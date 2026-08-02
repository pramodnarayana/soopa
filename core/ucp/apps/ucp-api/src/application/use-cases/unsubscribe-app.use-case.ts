import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';

@Injectable()
export class UnsubscribeAppUseCase {
  private readonly logger = new Logger(UnsubscribeAppUseCase.name);

  constructor(@Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository) {}

  async execute(tenantId: string, appSlug: string): Promise<void> {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) {
      this.logger.error(`Failed to unsubscribe app: Tenant ${tenantId} not found`);
      throw new NotFoundException('Tenant not found');
    }

    this.logger.log(
      `Tenant ${tenant.id} (${tenant.name}) initiating unsubscription from app: ${appSlug}`,
    );
    tenant.unsubscribeFromApp(appSlug);
    await this.tenantRepo.save(tenant);
    this.logger.log(
      `Tenant ${tenant.id} successfully unsubscribed from app: ${appSlug}. Domain events dispatched.`,
    );
  }
}
