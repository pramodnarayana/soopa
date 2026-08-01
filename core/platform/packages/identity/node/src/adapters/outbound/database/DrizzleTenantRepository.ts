import {
  createDbClient,
  generateId,
  tenants,
  tenantUsers,
  UserRoles,
  users,
} from '@soopa/database';
import { eq } from 'drizzle-orm';
import { IdentityInfrastructureError } from '../../../domain/Errors.js';
import type { TenantRepository, UserData } from '../../../ports/TenantRepository.js';

export class DrizzleTenantRepository implements TenantRepository {
  constructor(private readonly db: ReturnType<typeof createDbClient>['db']) {}

  async findUserByEmail(email: string): Promise<UserData | null> {
    try {
      const existingUser = await this.db
        .select()
        .from(users)
        .where(eq(users.email as never, email))
        .limit(1);
      return existingUser.length > 0 ? existingUser[0] : null;
    } catch (e: unknown) {
      let msg = typeof e === 'string' ? e : 'Unknown Error';
      if (e instanceof Error) msg = e.message;
      else if (typeof e === 'object' && e !== null) {
        try {
          msg = JSON.stringify(e, Object.getOwnPropertyNames(e));
        } catch {
          msg = '[Unserializable Error Object]';
        }
      }
      throw new IdentityInfrastructureError(`Failed to fetch user by email: ${msg}`);
    }
  }

  async provisionUserAndTenant(
    email: string,
    name: string,
    idpTenantId?: string,
  ): Promise<{ userId: string; tenantId: string }> {
    try {
      type DbType = ReturnType<typeof createDbClient>['db'];
      type TxType = Parameters<Parameters<DbType['transaction']>[0]>[0];
      return await this.db.transaction(async (tx: TxType) => {
        const userId = generateId('usr');
        const [newUser] = await tx.insert(users).values({ id: userId, email, name }).returning();

        let tenantIdToLink: string;

        if (idpTenantId) {
          const existingTenants = await tx
            .select()
            .from(tenants)
            .where(eq(tenants.idpTenantId as never, idpTenantId))
            .limit(1);

          if (existingTenants.length > 0) {
            tenantIdToLink = existingTenants[0].id;
          } else {
            const newTenantId = generateId('ten');
            const [newTenant] = await tx
              .insert(tenants)
              .values({
                id: newTenantId,
                name: `${name}'s Organization`,
                idpTenantId,
              })
              .returning();
            tenantIdToLink = newTenant.id;
          }
        } else {
          const newTenantId = generateId('ten');
          const [newTenant] = await tx
            .insert(tenants)
            .values({
              id: newTenantId,
              name: `${name}'s Organization`,
              idpTenantId: null,
            })
            .returning();
          tenantIdToLink = newTenant.id;
        }

        await tx.insert(tenantUsers).values({
          tenantId: tenantIdToLink,
          userId: newUser.id,
          role: UserRoles.ADMIN,
        });

        return { userId: newUser.id, tenantId: tenantIdToLink };
      });
    } catch (e: unknown) {
      let msg = typeof e === 'string' ? e : 'Unknown Error';
      if (e instanceof Error) msg = e.message;
      else if (typeof e === 'object' && e !== null) {
        try {
          msg = JSON.stringify(e, Object.getOwnPropertyNames(e));
        } catch {
          msg = '[Unserializable Error Object]';
        }
      }
      throw new IdentityInfrastructureError(`Failed to provision user and tenant: ${msg}`);
    }
  }

  async getTenantMappingForUser(userId: string): Promise<string | null> {
    try {
      const mapping = await this.db
        .select()
        .from(tenantUsers)
        .where(eq(tenantUsers.userId as never, userId))
        .limit(1);
      return mapping.length > 0 ? mapping[0].tenantId : null;
    } catch (e: unknown) {
      let msg = typeof e === 'string' ? e : 'Unknown Error';
      if (e instanceof Error) msg = e.message;
      else if (typeof e === 'object' && e !== null) {
        try {
          msg = JSON.stringify(e, Object.getOwnPropertyNames(e));
        } catch {
          msg = '[Unserializable Error Object]';
        }
      }
      throw new IdentityInfrastructureError(`Failed to fetch tenant mapping: ${msg}`);
    }
  }
}
