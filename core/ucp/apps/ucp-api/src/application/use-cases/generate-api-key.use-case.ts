import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { IsArray, IsNotEmpty, IsString } from 'class-validator';
import { ApiKey } from '../../domain/models/api-key.model.js';
import type { IApiKeyRepository } from '../../ports/outbound/api-key.repository.js';
import { API_KEY_REPOSITORY } from '../../ports/outbound/api-key.repository.js';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';

export class GenerateApiKeyDto {
  @IsString()
  @IsNotEmpty()
  tenantId!: string;

  @IsString()
  @IsNotEmpty()
  name!: string;

  @IsArray()
  @IsString({ each: true })
  @IsNotEmpty()
  scopes!: string[];
}

@Injectable()
export class GenerateApiKeyUseCase {
  constructor(
    @Inject(API_KEY_REPOSITORY) private readonly apiKeyRepo: IApiKeyRepository,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
  ) {}

  async execute(
    dto: GenerateApiKeyDto,
  ): Promise<{ apiKey: ApiKey; rawSecret: string }> {
    const tenant = await this.tenantRepo.findById(dto.tenantId);
    if (!tenant) {
      throw new NotFoundException(`Tenant with id ${dto.tenantId} not found`);
    }

    const { apiKey, rawSecret } = ApiKey.generate(
      dto.tenantId,
      dto.name,
      dto.scopes,
    );
    const savedKey = await this.apiKeyRepo.save(apiKey);

    return { apiKey: savedKey, rawSecret };
  }
}
