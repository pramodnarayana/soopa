import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { tenantUsers, users } from '@soopa/database';
import { and, eq, inArray, notExists } from 'drizzle-orm';
import { User } from '../../../domain/models/user.model.js';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import { IUserRepository } from '../../../ports/outbound/user.repository.js';

@Injectable()
export class UserDrizzleRepository implements IUserRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  async upsertUser(user: {
    id: string;
    idpUserId?: string;
    email?: string;
    name: string;
  }): Promise<void> {
    if (!user.email) {
      throw new Error(`Email is required for user ${user.id}`);
    }

    if (!user.idpUserId) {
      throw new Error(`idpUserId is required for upsert to prevent duplicate users`);
    }

    await this.db
      .insert(users)
      .values({
        id: user.id,
        idpUserId: user.idpUserId,
        email: user.email,
        name: user.name,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: users.idpUserId,
        set: {
          email: user.email,
          name: user.name,
          updatedAt: new Date(),
        },
      });
  }

  async findById(userId: string): Promise<User | null> {
    const results = await this.db.select().from(users).where(eq(users.id, userId)).limit(1);

    const raw = results[0];
    if (!raw) return null;

    return new User(
      raw.id,
      raw.idpUserId,
      raw.email,
      raw.name,
      raw.status,
      raw.createdAt,
      raw.updatedAt,
    );
  }

  async save(user: User): Promise<void> {
    await this.db
      .update(users)
      .set({
        name: user.name,
        status: user.status,
        updatedAt: user.updatedAt,
      })
      .where(eq(users.id, user.id));
  }

  async findByIdpUserId(idpUserId: string) {
    const results = await this.db
      .select()
      .from(users)
      .where(eq(users.idpUserId, idpUserId))
      .limit(1);
    return results[0] || null;
  }

  async findByEmail(email: string) {
    const results = await this.db.select().from(users).where(eq(users.email, email)).limit(1);
    return results[0] || null;
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

  async updateUserStatus(userId: string, status: 'active' | 'inactive'): Promise<void> {
    await this.db.update(users).set({ status, updatedAt: new Date() }).where(eq(users.id, userId));
  }

  async removeTenantUser(tenantId: string, userId: string): Promise<void> {
    await this.db
      .delete(tenantUsers)
      .where(and(eq(tenantUsers.tenantId, tenantId), eq(tenantUsers.userId, userId)));
  }

  async deleteOrphanedUsers(userIds: string[]): Promise<void> {
    if (userIds.length === 0) return;

    await this.db
      .delete(users)
      .where(
        and(
          inArray(users.id, userIds),
          notExists(this.db.select().from(tenantUsers).where(eq(tenantUsers.userId, users.id))),
        ),
      );
  }

  async findUsersByTenant(tenantId: string): Promise<
    {
      id: string;
      idpUserId: string | null;
      email: string;
      name: string;
      status: string;
      role: string;
      createdAt: Date;
    }[]
  > {
    const results = await this.db
      .select({
        id: users.id,
        idpUserId: users.idpUserId,
        email: users.email,
        name: users.name,
        status: users.status,
        role: tenantUsers.role,
        createdAt: tenantUsers.createdAt,
      })
      .from(tenantUsers)
      .innerJoin(users, eq(tenantUsers.userId, users.id))
      .where(eq(tenantUsers.tenantId, tenantId));

    return results;
  }
}
