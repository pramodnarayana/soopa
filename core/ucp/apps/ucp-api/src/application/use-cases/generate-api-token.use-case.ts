import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { ApiToken } from '../../domain/models/api-token.model.js';
import type { IApiTokenRepository } from '../../ports/outbound/api-token.repository.js';
import { API_TOKEN_REPOSITORY } from '../../ports/outbound/api-token.repository.js';
import type { ITenantRepository } from '../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../ports/outbound/tenant.repository.js';

export class GenerateApiTokenDto {
  @IsString()
  @IsNotEmpty()
  tenantId!: string;

  @IsString()
  @IsNotEmpty()
  name!: string;

  @IsOptional()
  expiresAt?: Date;
}

@Injectable()
export class GenerateApiTokenUseCase {
  constructor(
    @Inject(API_TOKEN_REPOSITORY)
    private readonly apiTokenRepo: IApiTokenRepository,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
  ) {}

  async execute(dto: GenerateApiTokenDto): Promise<{ apiToken: ApiToken; rawSecret: string }> {
    const tenant = await this.tenantRepo.findById(dto.tenantId);
    if (!tenant) {
      throw new NotFoundException(`Tenant with id ${dto.tenantId} not found`);
    }

    const { apiToken, rawSecret } = ApiToken.generate(dto.tenantId, dto.name, dto.expiresAt);

    await this.apiTokenRepo.save(apiToken);

    return { apiToken, rawSecret };
  }
}
