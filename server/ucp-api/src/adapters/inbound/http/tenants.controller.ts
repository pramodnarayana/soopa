import {
  Controller,
  Post,
  Body,
  Get,
  Inject,
  Patch,
  Delete,
  Param,
  NotFoundException,
} from '@nestjs/common';

import {
  ProvisionTenantUseCase,
  ProvisionTenantDto,
} from '../../../application/use-cases/provision-tenant.use-case';
import { TENANT_REPOSITORY } from '../../../ports/outbound/tenant.repository';
import type { ITenantRepository } from '../../../ports/outbound/tenant.repository';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider';
import type { IProjectProvider } from '../../../ports/outbound/project.provider';
import { ORGANIZATION_PROVIDER } from '../../../ports/outbound/organization.provider';
import type { IOrganizationProvider } from '../../../ports/outbound/organization.provider';

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
  async updateName(@Param('id') id: string, @Body('name') name: string) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.rename(name);
    await this.tenantRepo.save(tenant);
    return tenant;
  }

  @Patch(':id/status')
  async updateStatus(
    @Param('id') id: string,
    @Body('status') status: 'active' | 'inactive',
  ) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');
    tenant.changeStatus(status);
    await this.tenantRepo.save(tenant);
    return tenant;
  }

  @Delete(':id')
  async delete(@Param('id') id: string) {
    const tenant = await this.tenantRepo.findById(id);
    if (!tenant) throw new NotFoundException('Tenant not found');

    // Delete from Identity Provider first to ensure we don't leave orphaned organizations
    if (tenant.zitadelOrgId) {
      try {
        await this.organizationProvider.deleteOrganization(tenant.zitadelOrgId);
      } catch (err) {
        // Log the error but proceed with deleting from DB if Zitadel fails (e.g. if already deleted)
        console.error(
          `Warning: Failed to delete organization ${tenant.zitadelOrgId} from Zitadel`,
          err,
        );
      }
    }

    await this.tenantRepo.delete(id);
    return { success: true };
  }
}
