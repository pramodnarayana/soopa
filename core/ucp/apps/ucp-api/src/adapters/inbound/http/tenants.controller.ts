import {
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  Inject,
  NotFoundException,
  Param,
  Patch,
  Post,
  UseGuards,
  UsePipes,
  ValidationPipe,
} from '@nestjs/common';
import { IsIn, IsNotEmpty, IsString } from 'class-validator';
import { DeleteTenantUseCase } from '../../../application/use-cases/delete-tenant.use-case.js';
import {
  ProvisionTenantDto,
  ProvisionTenantUseCase,
} from '../../../application/use-cases/provision-tenant.use-case.js';
import type { IOrganizationProvider } from '../../../ports/outbound/organization.provider.js';
import { ORGANIZATION_PROVIDER } from '../../../ports/outbound/organization.provider.js';
import type { IProjectProvider } from '../../../ports/outbound/project.provider.js';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider.js';
import type { ITenantRepository } from '../../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../../ports/outbound/tenant.repository.js';

export class UpdateTenantNameDto {
  @IsString()
  @IsNotEmpty()
  name!: string;
}

export class UpdateTenantStatusDto {
  @IsString()
  @IsNotEmpty()
  @IsIn(['active', 'inactive'])
  status!: 'active' | 'inactive';
}

import { PlatformAuthGuard } from './guards/platform-auth.guard.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

@Controller('tenants')
export class TenantsController {
  constructor(
    private readonly provisionTenantUseCase: ProvisionTenantUseCase,
    private readonly deleteTenantUseCase: DeleteTenantUseCase,

    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
    @Inject(ORGANIZATION_PROVIDER)
    private readonly organizationProvider: IOrganizationProvider,
  ) {}

  @Get()
  @UseGuards(PlatformAuthGuard)
  async findAll() {
    const tenants = await this.tenantRepo.findAll();
    return tenants;
  }

  @Get('roles')
  @UseGuards(PlatformAuthGuard)
  async getRoles() {
    const roles = await this.projectProvider.getRoles();
    const tenantGroup = process.env.ZITADEL_TENANT_ROLE_GROUP || 'Tenant';
    return roles.filter((role) => role.group === tenantGroup);
  }

  private async resolveTenant(id: string) {
    let tenant = await this.tenantRepo.findById(id);
    if (!tenant) {
      tenant = await this.tenantRepo.findByIdpTenantId(id);
    }
    return tenant;
  }

  @Get(':id')
  @UseGuards(TenantAuthGuard)
  async findOne(@Param('id') id: string) {
    const tenant = await this.resolveTenant(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    return tenant;
  }

  @Post()
  @UseGuards(PlatformAuthGuard)
  async provision(
    @Body() dto: ProvisionTenantDto,
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    const tenant = await this.provisionTenantUseCase.execute(dto, idempotencyKey);
    return tenant;
  }

  @Patch(':id/name')
  @UseGuards(TenantAuthGuard)
  @UsePipes(new ValidationPipe({ transform: true, whitelist: true }))
  async updateName(
    @Param('id') id: string,
    @Body() dto: UpdateTenantNameDto,
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    const tenant = await this.resolveTenant(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.rename(dto.name);
    await this.tenantRepo.save(tenant, idempotencyKey);
    return tenant;
  }

  @Patch(':id/status')
  @UseGuards(PlatformAuthGuard)
  @UsePipes(new ValidationPipe({ transform: true, whitelist: true }))
  async updateStatus(
    @Param('id') id: string,
    @Body() dto: UpdateTenantStatusDto,
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    const tenant = await this.resolveTenant(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.changeStatus(dto.status);
    await this.tenantRepo.save(tenant, idempotencyKey);
    return tenant;
  }

  @Delete(':id')
  @UseGuards(PlatformAuthGuard)
  async delete(@Param('id') id: string, @Headers('idempotency-key') idempotencyKey?: string) {
    const tenant = await this.resolveTenant(id);
    if (!tenant) throw new NotFoundException('Tenant not found');

    await this.deleteTenantUseCase.execute(tenant.id, idempotencyKey);
    return { success: true };
  }
}
