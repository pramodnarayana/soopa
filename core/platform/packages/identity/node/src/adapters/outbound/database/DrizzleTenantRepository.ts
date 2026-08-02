import { createDbClient, tenantUsers, users } from '@soopa/database';
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
      throw new IdentityInfrastructureError(
        `Failed to fetch user by email: ${this.serializeError(e)}`,
      );
    }
  }

  /**
   * Retrieves a user by their external IdP user ID (sub).
   * This is a read-only operation. JIT provisioning is an anti-pattern and should not be done here.
   */
  async findUserByIdpId(idpUserId: string): Promise<UserData | null> {
    try {
      const byIdp = await this.db
        .select()
        .from(users)
        .where(eq(users.idpUserId as never, idpUserId))
        .limit(1);
      return byIdp.length > 0 ? byIdp[0] : null;
    } catch (e: unknown) {
      throw new IdentityInfrastructureError(
        `Failed to fetch user by IDP ID: ${this.serializeError(e)}`,
      );
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
      throw new IdentityInfrastructureError(
        `Failed to fetch tenant mapping: ${this.serializeError(e)}`,
      );
    }
  }

  private serializeError(e: unknown): string {
    if (typeof e === 'string') return e;
    if (e instanceof Error) return e.message;
    if (typeof e === 'object' && e !== null) {
      try {
        return JSON.stringify(e, Object.getOwnPropertyNames(e));
      } catch {
        return '[Unserializable Error Object]';
      }
    }
    return 'Unknown Error';
  }
}
