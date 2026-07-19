import type { TenantRepository, UserData } from '../../../ports/TenantRepository.js';
import { users, tenants, tenantUsers, createDbClient, UserRoles } from '@soopa/database';
import { eq } from 'drizzle-orm';
import { IdentityInfrastructureError } from '../../../domain/Errors.js';

export class DrizzleTenantRepository implements TenantRepository {
  constructor(private readonly db: ReturnType<typeof createDbClient>) {} // Inject Drizzle instance

  async findUserByEmail(email: string): Promise<UserData | null> {
    try {
      // @ts-expect-error - Drizzle monorepo type mismatch
      const existingUser = await this.db.select().from(users).where(eq(users.email as never, email)).limit(1);
      return existingUser.length > 0 ? existingUser[0] : null;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new IdentityInfrastructureError(`Failed to fetch user by email: ${msg}`);
    }
  }

  async provisionUserAndTenant(email: string, name: string, zitadelOrgId?: string): Promise<{ userId: string; tenantId: string; }> {
    try {
      const [newUser] = await this.db.insert(users).values({ email, name }).returning();
      const [newTenant] = await this.db.insert(tenants).values({
        name: `${name}'s Organization`,
        zitadelOrgId: zitadelOrgId || null
      }).returning();
      
      await this.db.insert(tenantUsers).values({
        tenantId: newTenant.id,
        userId: newUser.id,
        role: UserRoles.ADMIN
      });

      return { userId: newUser.id, tenantId: newTenant.id };
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new IdentityInfrastructureError(`Failed to provision user and tenant: ${msg}`);
    }
  }

  async getTenantMappingForUser(userId: string): Promise<string | null> {
    try {
      // @ts-expect-error - Drizzle monorepo type mismatch
      const mapping = await this.db.select().from(tenantUsers).where(eq(tenantUsers.userId as never, userId)).limit(1);
      return mapping.length > 0 ? mapping[0].tenantId : null;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new IdentityInfrastructureError(`Failed to fetch tenant mapping: ${msg}`);
    }
  }
}
