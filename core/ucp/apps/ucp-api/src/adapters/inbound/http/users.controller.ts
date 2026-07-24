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
} from '@nestjs/common';
import { IsEmail, IsNotEmpty, IsString } from 'class-validator';
import { ZitadelUserState } from '../../../domain/enums/zitadel-user-state.enum.js';
import type { ITenantRepository } from '../../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../../ports/outbound/tenant.repository.js';
import type { IUserRepository } from '../../../ports/outbound/user.repository.js';
import { USER_REPOSITORY } from '../../../ports/outbound/user.repository.js';
import type { IUserIdentityProvider } from '../../../ports/outbound/user-identity.provider.js';
import { USER_IDENTITY_PROVIDER } from '../../../ports/outbound/user-identity.provider.js';

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
export class UsersController {
  constructor(
    @Inject(USER_IDENTITY_PROVIDER)
    private readonly userIdentityProvider: IUserIdentityProvider,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
    @Inject(USER_REPOSITORY) private readonly userRepo: IUserRepository,
  ) {}

  @Get()
  async getUsers(@Param('tenantId') tenantId: string) {
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
          state: ZitadelUserState.ACTIVE, // Stubbed for local model
          role: u.role,
          createdAt: u.createdAt,
        };
      }),
    };
  }

  @Post()
  async createUser(
    @Param('tenantId') tenantId: string,
    @Body() dto: CreateUserDto,
  ) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.zitadelOrgId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    const result = await this.userIdentityProvider.inviteUser(
      tenant.zitadelOrgId,
      dto.email,
      dto.role,
      dto.firstName,
      dto.lastName,
    );

    // Dual-write immediately so the UI is responsive, webhook will act as fallback for out-of-band changes
    await this.userRepo.upsertUser({
      id: result.userId,
      email: dto.email,
      name: `${dto.firstName} ${dto.lastName}`.trim(),
    });

    await this.userRepo.upsertTenantUser({
      tenantId: tenant.id,
      userId: result.userId,
      role: dto.role,
    });

    return result;
  }

  @Patch(':userId')
  async updateUser(
    @Param('tenantId') tenantId: string,
    @Param('userId') userId: string,
    @Body() dto: UpdateUserDto,
  ) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.zitadelOrgId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    // Verify user belongs to this tenant
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const userBelongsToTenant = tenantUsers.some((u) => u.id === userId);
    if (!userBelongsToTenant) {
      throw new NotFoundException('User not found in this tenant');
    }

    await this.userIdentityProvider.updateUser(
      userId,
      tenant.zitadelOrgId,
      dto.firstName,
      dto.lastName,
      dto.role,
    );

    // Dual-write to sync local read model
    await this.userRepo.upsertUser({
      id: userId,
      name: `${dto.firstName} ${dto.lastName}`.trim(),
    });

    await this.userRepo.upsertTenantUser({
      tenantId: tenant.id,
      userId: userId,
      role: dto.role,
    });

    return { success: true };
  }

  @Patch(':userId/status')
  async toggleUserStatus(
    @Param('tenantId') tenantId: string,
    @Param('userId') userId: string,
    @Body() dto: ToggleUserStatusDto,
  ) {
    const tenant = await this.tenantRepo.findById(tenantId);
    if (!tenant) throw new NotFoundException('Tenant not found');

    if (!tenant.zitadelOrgId) {
      throw new BadRequestException('Tenant has no associated organization');
    }

    // Verify user belongs to this tenant
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const userBelongsToTenant = tenantUsers.some((u) => u.id === userId);
    if (!userBelongsToTenant) {
      throw new NotFoundException('User not found in this tenant');
    }

    await this.userIdentityProvider.toggleUserStatus(
      userId,
      tenant.zitadelOrgId,
      dto.action,
    );
    return { success: true };
  }

  @Delete(':userId')
  async deleteUser(
    @Param('tenantId') tenantId: string,
    @Param('userId') userId: string,
  ) {
    // Verify user belongs to this tenant
    const tenantUsers = await this.userRepo.findUsersByTenant(tenantId);
    const userBelongsToTenant = tenantUsers.some((u) => u.id === userId);
    if (!userBelongsToTenant) {
      throw new NotFoundException('User not found in this tenant');
    }

    await this.userIdentityProvider.deleteUser(userId);

    // Update local read model
    await this.userRepo.removeTenantUser(tenantId, userId);

    return { success: true };
  }
}
