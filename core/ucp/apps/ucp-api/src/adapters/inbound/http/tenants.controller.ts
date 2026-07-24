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
  UsePipes,
  ValidationPipe,
} from '@nestjs/common';
import { IsIn, IsNotEmpty, IsString } from 'class-validator';
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

@Controller('tenants')
export class TenantsController {
  constructor(
    private readonly provisionTenantUseCase: ProvisionTenantUseCase,

    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
    @Inject(ORGANIZATION_PROVIDER)
    private readonly organizationProvider: IOrganizationProvider,
  ) {}

  @Get()
  async findAll() {
    const tenants = await this.tenantRepo.findAll();
    return tenants;
  }

  @Get('roles')
  async getRoles() {
    const roles = await this.projectProvider.getRoles();
    const tenantGroup = process.env.ZITADEL_TENANT_ROLE_GROUP || 'Tenant';
    return roles.filter((role) => role.group === tenantGroup);
  }

  @Post()
  async provision(@Body() dto: ProvisionTenantDto) {
    const tenant = await this.provisionTenantUseCase.execute(dto);
    return tenant;
  }

  @Patch(':id/name')
  @UsePipes(new ValidationPipe({ transform: true, whitelist: true }))
  async updateName(@Param('id') id: string, @Body() dto: UpdateTenantNameDto) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.rename(dto.name);
    await this.tenantRepo.save(tenant);
    return tenant;
  }

  @Patch(':id/status')
  @UsePipes(new ValidationPipe({ transform: true, whitelist: true }))
  async updateStatus(
    @Param('id') id: string,
    @Body() dto: UpdateTenantStatusDto,
  ) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.changeStatus(dto.status);
    await this.tenantRepo.save(tenant);
    return tenant;
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');

    // Delete from database first (includes cascading deletion of dependent records)
    // This is done transactionally in the repository layer
    await this.tenantRepo.delete(id);

    // Then delete from Zitadel as best-effort cleanup
    if (tenant.zitadelOrgId) {
      try {
        await this.organizationProvider.deleteOrganization(tenant.zitadelOrgId);
      } catch (err) {
        // Log the error but don't fail the request since DB is already cleaned up
        console.error(
          `Warning: Failed to delete organization ${tenant.zitadelOrgId} from Zitadel`,
          err,
        );
      }
    }

    return { success: true };
  }
}
