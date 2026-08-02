import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { IsNotEmpty, IsString } from 'class-validator';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';

export class SubscribeAppDto {
  @IsString()
  @IsNotEmpty()
  appSlug!: string;
}

@Injectable()
export class SubscribeAppUseCase {
  private readonly logger = new Logger(SubscribeAppUseCase.name);

  constructor(@Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository) {}

  async execute(tenantId: string, dto: SubscribeAppDto): Promise<void> {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) {
      this.logger.error(`Failed to subscribe app: Tenant ${tenantId} not found`);
      throw new NotFoundException('Tenant not found');
    }

    this.logger.log(
      `Tenant ${tenant.id} (${tenant.name}) initiating subscription to app: ${dto.appSlug}`,
    );
    tenant.subscribe(dto.appSlug);
    await this.tenantRepo.save(tenant);
    this.logger.log(
      `Tenant ${tenant.id} successfully subscribed to app: ${dto.appSlug}. Domain events dispatched.`,
    );
  }
}
