import { createDbClient, generateId, sql, users } from '@soopa/database';
import { v4 as uuidv4 } from 'uuid';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { DrizzleTenantRepository } from '../src/adapters/outbound/database/DrizzleTenantRepository.js';

describe('DrizzleTenantRepository', () => {
  let db: ReturnType<typeof createDbClient>['db'];
  let repo: DrizzleTenantRepository;
  const dbConnectionString =
    process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5432/ucp_global';

  beforeAll(async () => {
    db = createDbClient(dbConnectionString).db;
    repo = new DrizzleTenantRepository(db);
  });

  beforeEach(async () => {
    // Clear out data to keep tests isolated
    await db.execute(sql`TRUNCATE TABLE ucp.tenants, ucp.users CASCADE`);
  });

  afterAll(async () => {
    // pg pool exits when the process ends
  });

  it('should find user by idpUserId', async () => {
    const email = `test-${uuidv4()}@example.com`;
    const idpUserId = `idp_${uuidv4()}`;
    const [newUser] = await db
      .insert(users)
      .values({ id: generateId('usr'), email, name: 'Test User', idpUserId })
      .returning();

    const user = await repo.findUserByIdpId(idpUserId);

    expect(user).toBeDefined();
    expect(user?.id).toBe(newUser.id);
    expect(user?.email).toBe(email);
  });

  it('findUserByIdpId should return null for non-existent user', async () => {
    const user = await repo.findUserByIdpId('doesnotexist');
    expect(user).toBeNull();
  });

  it('should handle findUserByEmail for non-existent user', async () => {
    const user = await repo.findUserByEmail('doesnotexist@example.com');
    expect(user).toBeNull();
  });

  it('should handle getTenantMappingForUser for user with no mapping', async () => {
    const email = `test-${uuidv4()}@example.com`;
    const [newUser] = await db
      .insert(users)
      .values({ id: generateId('usr'), email, name: 'No Mapping User' })
      .returning();

    const tenantId = await repo.getTenantMappingForUser(newUser.id);
    expect(tenantId).toBeNull();
  });

  it('should throw IdentityInfrastructureError on DB failure for findUserByEmail', async () => {
    const badDb = {
      select: () => {
        throw new Error('DB Error');
      },
    } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.findUserByEmail('test@example.com')).rejects.toThrow(
      'Failed to fetch user by email: DB Error',
    );
  });

  it('should throw IdentityInfrastructureError on DB failure for findUserByIdpId', async () => {
    const badDb = {
      select: () => ({
        from: () => ({ where: () => ({ limit: () => Promise.reject(new Error('DB Error')) }) }),
      }),
    } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.findUserByIdpId('test-idp-id')).rejects.toThrow(
      'Failed to fetch user by IDP ID: DB Error',
    );
  });

  it('should throw IdentityInfrastructureError on DB failure for getTenantMappingForUser', async () => {
    const badDb = {
      select: () => {
        throw new Error('DB Error');
      },
    } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.getTenantMappingForUser('123')).rejects.toThrow(
      'Failed to fetch tenant mapping: DB Error',
    );
  });
});
