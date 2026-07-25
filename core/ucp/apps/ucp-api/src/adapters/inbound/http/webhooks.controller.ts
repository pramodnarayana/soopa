import {
  Body,
  Controller,
  Delete,
  Get,
  Inject,
  NotFoundException,
  Param,
  Patch,
  Post,
  UseGuards,
} from '@nestjs/common';
import { IsBoolean, IsNotEmpty, IsOptional, IsString, IsUrl } from 'class-validator';
import { CreateWebhookUseCase } from '../../../application/use-cases/create-webhook.use-case.js';
import type { IWebhookRepository } from '../../../ports/outbound/webhook.repository.js';
import { WEBHOOK_REPOSITORY } from '../../../ports/outbound/webhook.repository.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

export class CreateWebhookRequestDto {
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

export class UpdateWebhookRequestDto {
  @IsOptional()
  @IsString()
  name?: string;

  @IsOptional()
  @IsString()
  @IsUrl()
  url?: string;

  @IsOptional()
  @IsBoolean()
  active?: boolean;
}

@Controller('tenants/:tenantId/webhooks')
@UseGuards(TenantAuthGuard)
export class WebhooksController {
  constructor(
    private readonly createWebhookUseCase: CreateWebhookUseCase,
    @Inject(WEBHOOK_REPOSITORY)
    private readonly webhookRepo: IWebhookRepository,
  ) {}

  @Post()
  async create(@Param('tenantId') tenantId: string, @Body() dto: CreateWebhookRequestDto) {
    const webhook = await this.createWebhookUseCase.execute({
      tenantId,
      name: dto.name,
      url: dto.url,
      authHeaderVaultRef: dto.authHeaderVaultRef,
    });

    return {
      id: webhook.id,
      name: webhook.name,
      url: webhook.url,
      active: webhook.active,
      createdAt: webhook.createdAt,
    };
  }

  @Get()
  async findAll(@Param('tenantId') tenantId: string) {
    const webhooks = await this.webhookRepo.findAllByTenant(tenantId);
    return webhooks.map((w) => ({
      id: w.id,
      name: w.name,
      url: w.url,
      active: w.active,
      createdAt: w.createdAt,
    }));
  }

  @Patch(':id')
  async update(
    @Param('tenantId') tenantId: string,
    @Param('id') id: string,
    @Body() dto: UpdateWebhookRequestDto,
  ) {
    const webhook = await this.webhookRepo.findById(tenantId, id);
    if (!webhook) {
      throw new NotFoundException('Webhook not found');
    }

    const updatedWebhook = webhook.update({
      name: dto.name,
      url: dto.url,
      active: dto.active,
    });

    await this.webhookRepo.save(updatedWebhook);

    return {
      id: updatedWebhook.id,
      name: updatedWebhook.name,
      url: updatedWebhook.url,
      active: updatedWebhook.active,
      createdAt: updatedWebhook.createdAt,
    };
  }

  @Delete(':id')
  async remove(@Param('tenantId') tenantId: string, @Param('id') id: string) {
    await this.webhookRepo.delete(tenantId, id);
  }
}
