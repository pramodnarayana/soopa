import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { tenantUsers, users } from '@soopa/database';
import { and, eq } from 'drizzle-orm';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module.js';
import { IUserRepository } from '../../../ports/outbound/user.repository.js';

@Injectable()
export class UserDrizzleRepository implements IUserRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  async upsertUser(user: {
    id: string;
    email?: string;
    name: string;
  }): Promise<void> {
    if (!user.email) {
      throw new Error(`Email is required for user ${user.id}`);
    }

    await this.db
      .insert(users)
      .values({
        id: user.id,
        email: user.email,
        name: user.name,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: users.id,
        set: {
          email: user.email,
          name: user.name,
          updatedAt: new Date(),
        },
      });
  }

  async upsertTenantUser(tenantUser: {
    tenantId: string;
    userId: string;
    role: string;
  }): Promise<void> {
    await this.db
      .insert(tenantUsers)
      .values({
        tenantId: tenantUser.tenantId,
        userId: tenantUser.userId,
        role: tenantUser.role,
      })
      .onConflictDoUpdate({
        target: [tenantUsers.tenantId, tenantUsers.userId],
        set: {
          role: tenantUser.role,
        },
      });
  }

  async removeTenantUser(tenantId: string, userId: string): Promise<void> {
    await this.db
      .delete(tenantUsers)
      .where(
        and(eq(tenantUsers.tenantId, tenantId), eq(tenantUsers.userId, userId)),
      );
  }

  async findUsersByTenant(tenantId: string): Promise<
    {
      id: string;
      email: string;
      name: string;
      role: string;
      createdAt: Date;
    }[]
  > {
    const results = await this.db
      .select({
        id: users.id,
        email: users.email,
        name: users.name,
        role: tenantUsers.role,
        createdAt: tenantUsers.createdAt,
      })
      .from(tenantUsers)
      .innerJoin(users, eq(tenantUsers.userId, users.id))
      .where(eq(tenantUsers.tenantId, tenantId));

    return results;
  }
}
