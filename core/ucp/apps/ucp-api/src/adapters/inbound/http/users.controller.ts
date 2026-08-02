import {
  BadRequestException,
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
import { generateId } from '@soopa/database';
import { IsEmail, IsNotEmpty, IsString } from 'class-validator';
import { ToggleUserStatusUseCase } from '../../../application/use-cases/toggle-user-status.use-case.js';
import { ZitadelUserState } from '../../../domain/enums/zitadel-user-state.enum.js';
import type { ITenantRepository } from '../../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../../ports/outbound/tenant.repository.js';
import type { IUserRepository } from '../../../ports/outbound/user.repository.js';
import { USER_REPOSITORY } from '../../../ports/outbound/user.repository.js';
import type { IUserIdentityProvider } from '../../../ports/outbound/user-identity.provider.js';
import { USER_IDENTITY_PROVIDER } from '../../../ports/outbound/user-identity.provider.js';
import { UcpTenantId } from './decorators/ucp-tenant-id.decorator.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

export class CreateUserDto {
  @IsString()
  @IsNotEmpty()
  firstName!: string;

  @IsString()
  @IsNotEmpty()
  lastName!: string;

  @IsString()
  @IsEmail()
  @IsNotEmpty()
  email!: string;

  @IsString()
  @IsNotEmpty()
  role!: string;
}

export class ToggleUserStatusDto {
  @IsString()
  @IsNotEmpty()
  action!: 'activate' | 'deactivate';
}

export class UpdateUserDto {
  @IsString()
  @IsNotEmpty()
  firstName!: string;

  @IsString()
  @IsNotEmpty()
  lastName!: string;

  @IsString()
  @IsNotEmpty()
  role!: string;
}

@Controller('tenants/:tenantId/users')
@UseGuards(TenantAuthGuard)
export class UsersController {
  constructor(
    @Inject(USER_IDENTITY_PROVIDER)
    private readonly userIdentityProvider: IUserIdentityProvider,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(USER_REPOSITORY) private readonly userRepo: IUserRepository,
    private readonly toggleUserStatusUseCase: ToggleUserStatusUseCase,
  ) {}

  @Get()
  async getUsers(@UcpTenantId() tenantId: string) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    // Read from optimized local read-model (Postgres) instead of querying Zitadel API
    const users = await this.userRepo.findUsersByTenant(tenantId);
    return {
      result: users.map((u) => {
        const nameParts = u.name.split(' ');
        const firstName = nameParts[0] || '';
        const lastName = nameParts.slice(1).join(' ') || '';
        return {
          id: u.id,
          email: u.email,
          displayName: u.name,
          firstName,
          lastName,
          state: u.status === 'inactive' ? ZitadelUserState.INACTIVE : ZitadelUserState.ACTIVE,
          role: u.role,
          createdAt: u.createdAt,
        };
      }),
    };
  }

  @Post()
  async createUser(@UcpTenantId() tenantId: string, @Body() dto: CreateUserDto) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.idpTenantId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    const result = await this.userIdentityProvider.inviteUser(
      tenant.idpTenantId,
      dto.email,
      dto.role,
      dto.firstName,
      dto.lastName,
    );

    // Dual-write immediately so the UI is responsive, webhook will act as fallback for out-of-band changes
    const localUserId = generateId('usr');
    await this.userRepo.upsertUser({
      id: localUserId,
      idpUserId: result.userId,
      email: dto.email,
      name: `${dto.firstName} ${dto.lastName}`.trim(),
    });

    await this.userRepo.upsertTenantUser({
      tenantId: tenant.id,
      userId: localUserId,
      role: dto.role,
    });

    // Return the local UCP identity to the client
    return { ...result, userId: localUserId, idpUserId: result.userId };
  }

  @Patch(':id')
  async updateUser(
    @UcpTenantId() tenantId: string,
    @Param('id') userId: string,
    @Body() dto: UpdateUserDto,
  ) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.idpTenantId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    // Verify user belongs to this tenant and get user details
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const user = tenantUsers.find((u) => u.id === userId);
    if (!user || !user.idpUserId) {
      throw new NotFoundException('User identity mapping not found in this tenant');
    }

    await this.userIdentityProvider.updateUser(
      user.idpUserId,
      tenant.idpTenantId,
      dto.firstName,
      dto.lastName,
      dto.role,
    );

    // Dual-write to sync local read model
    await this.userRepo.upsertUser({
      id: userId,
      idpUserId: user.idpUserId,
      email: user.email,
      name: `${dto.firstName} ${dto.lastName}`.trim(),
    });

    await this.userRepo.upsertTenantUser({
      tenantId: tenant.id,
      userId: userId,
      role: dto.role,
    });

    return { success: true };
  }

  @Patch(':id/status')
  async toggleStatus(
    @UcpTenantId() tenantId: string,
    @Param('id') userId: string,
    @Body() dto: ToggleUserStatusDto,
  ) {
    await this.toggleUserStatusUseCase.execute(tenantId, userId, dto.action);
    return { success: true };
  }

  @Delete(':id')
  async deleteUser(@UcpTenantId() tenantId: string, @Param('id') userId: string) {
    // Verify user belongs to this tenant and get user details
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const user = tenantUsers.find((u) => u.id === userId);
    if (!user || !user.idpUserId) {
      throw new NotFoundException('User identity mapping not found in this tenant');
    }

    await this.userIdentityProvider.deleteUser(user.idpUserId);

    // Update local read model
    await this.userRepo.removeTenantUser(tenantId, userId);

    return { success: true };
  }
}
