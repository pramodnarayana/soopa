import {
  Body,
  Controller,
  Delete,
  Get,
  Inject,
  Param,
  Patch,
  Post,
  UseGuards,
} from '@nestjs/common';
import { IsBoolean, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { GenerateApiTokenUseCase } from '../../../application/use-cases/generate-api-token.use-case.js';
import type { IApiTokenRepository } from '../../../ports/outbound/api-token.repository.js';
import { API_TOKEN_REPOSITORY } from '../../../ports/outbound/api-token.repository.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

export class GenerateApiTokenRequestDto {
  @IsString()
  @IsNotEmpty()
  name!: string;
}

export class UpdateApiTokenRequestDto {
  @IsOptional()
  @IsString()
  name?: string;

  @IsOptional()
  @IsBoolean()
  active?: boolean;
}

@Controller('tenants/:tenantId/tokens')
@UseGuards(TenantAuthGuard)
export class ApiTokensController {
  constructor(
    private readonly generateApiTokenUseCase: GenerateApiTokenUseCase,
    @Inject(API_TOKEN_REPOSITORY)
    private readonly tokenRepo: IApiTokenRepository,
  ) {}

  @Post()
  async generate(@Param('tenantId') tenantId: string, @Body() dto: GenerateApiTokenRequestDto) {
    const result = await this.generateApiTokenUseCase.execute({
      tenantId,
      name: dto.name,
    });

    return {
      id: result.apiToken.id,
      client_id: result.apiToken.clientId,
      name: result.apiToken.name,
      active: result.apiToken.active,
      createdAt: result.apiToken.createdAt,
      client_secret: result.rawSecret, // only returned once
    };
  }

  @Get()
  async findAll(@Param('tenantId') tenantId: string) {
    const tokens = await this.tokenRepo.findAllByTenant(tenantId);
    return tokens.map((t) => ({
      id: t.id,
      client_id: t.clientId,
      name: t.name,
      active: t.active,
      createdAt: t.createdAt,
    }));
  }

  @Patch(':id')
  async update(
    @Param('tenantId') tenantId: string,
    @Param('id') id: string,
    @Body() dto: UpdateApiTokenRequestDto,
  ) {
    const token = await this.tokenRepo.findById(tenantId, id);
    if (!token) {
      throw new Error('Token not found');
    }
    const updatedToken = token.update({
      name: dto.name,
      active: dto.active,
    });

    await this.tokenRepo.save(updatedToken);
    return updatedToken;
  }

  @Delete(':id')
  async remove(@Param('tenantId') tenantId: string, @Param('id') id: string) {
    await this.tokenRepo.delete(tenantId, id);
  }
}
