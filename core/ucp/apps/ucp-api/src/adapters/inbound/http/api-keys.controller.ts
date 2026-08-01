/* eslint-disable */
import { Body, Controller, Param, Post, UseGuards } from '@nestjs/common';
import { UcpTenantId } from './decorators/ucp-tenant-id.decorator.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';
import { IsArray, IsNotEmpty, IsString } from 'class-validator';
import { GenerateApiKeyUseCase } from '../../../application/use-cases/generate-api-key.use-case.js';

export class CreateApiKeyRequestDto {
  @IsString()
  @IsNotEmpty()
  name!: string;

  @IsArray()
  @IsString({ each: true })
  @IsNotEmpty()
  scopes!: string[];
}

@Controller('tenants/:tenantId/keys')
@UseGuards(TenantAuthGuard)
export class ApiKeysController {
  constructor(private readonly generateApiKeyUseCase: GenerateApiKeyUseCase) {}

  @Post()
  async generate(
    @UcpTenantId() tenantId: string,
    @Body() dto: CreateApiKeyRequestDto,
  ) {
    const result = await this.generateApiKeyUseCase.execute({
      tenantId,
      name: dto.name,
      scopes: dto.scopes,
    });

    // We return the rawSecret ONCE to the user.
    return {
      apiKey: result.apiKey,
      rawSecret: result.rawSecret,
    };
  }
}
