import { Controller, Post, Body, Get, Param } from '@nestjs/common';
import {
  ProvisionTenantUseCase,
  ProvisionTenantDto,
} from '../../../application/use-cases/provision-tenant.use-case';

@Controller('tenants')
export class TenantsController {
  constructor(
    private readonly provisionTenantUseCase: ProvisionTenantUseCase,
  ) {}

  @Post()
  async provision(@Body() dto: ProvisionTenantDto) {
    const tenant = await this.provisionTenantUseCase.execute(dto);
    return tenant;
  }
}
