import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { IsNotEmpty, IsOptional, IsString, IsUrl } from 'class-validator';
import * as crypto from 'crypto';
import { Webhook } from '../../domain/models/webhook.model.js';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';
import type { IWebhookRepository } from '../../ports/outbound/webhook.repository.js';
import { WEBHOOK_REPOSITORY } from '../../ports/outbound/webhook.repository.js';

export class CreateWebhookDto {
  @IsString()
  @IsNotEmpty()
  tenantId!: string;

  @IsString()
  @IsNotEmpty()
  name!: string;

  @IsString()
  @IsNotEmpty()
  @IsUrl()
  url!: string;

  @IsOptional()
  @IsString()
  authHeaderVaultRef?: string;
}

@Injectable()
export class CreateWebhookUseCase {
  constructor(
    @Inject(WEBHOOK_REPOSITORY)
    private readonly webhookRepo: IWebhookRepository,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
  ) {}

  async execute(dto: CreateWebhookDto): Promise<Webhook> {
    const tenant = await this.tenantRepo.findById(dto.tenantId);
    if (!tenant) {
      throw new NotFoundException(`Tenant with id ${dto.tenantId} not found`);
    }

    const id = `wh_${crypto.randomBytes(12).toString('hex')}`;
    const webhook = Webhook.create(
      id,
      dto.tenantId,
      dto.name,
      dto.url,
      dto.authHeaderVaultRef || null,
    );

    await this.webhookRepo.save(webhook);

    return webhook;
  }
}
