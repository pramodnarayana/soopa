import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { DrizzleTenantRepository } from '../src/adapters/outbound/database/DrizzleTenantRepository.js';
import { createDbClient } from '@soopa/database';
import { users, tenants, tenantUsers } from '@soopa/database';
import { v4 as uuidv4 } from 'uuid';

describe('DrizzleTenantRepository', () => {
  let db: ReturnType<typeof createDbClient>['db'];
  let repo: DrizzleTenantRepository;
  const dbConnectionString = process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_platform';

  beforeAll(async () => {
    db = createDbClient(dbConnectionString).db;
    repo = new DrizzleTenantRepository(db);
  });
  
  beforeEach(async () => {
    // Clear out data to keep tests isolated. 
    // We only clear tenantUsers, users, tenants to avoid deleting other table data
    await db.delete(tenantUsers);
    await db.delete(tenants);
    await db.delete(users);
  });

  afterAll(async () => {
    // Close connection if needed (pg-postgres doesn't expose a close on the drizzle instance directly, 
    // but the node process will exit when tests finish)
  });

  it('should provision user and tenant correctly', async () => {
    const email = `test-${uuidv4()}@example.com`;
    const result = await repo.provisionUserAndTenant(email, 'Test Org', 'zitadel-org-1');
    
    expect(result.userId).toBeDefined();
    expect(result.tenantId).toBeDefined();

    const user = await repo.findUserByEmail(email);
    expect(user).toBeDefined();
    expect(user?.email).toBe(email);

    const tenantId = await repo.getTenantMappingForUser(result.userId);
    expect(tenantId).toBe(result.tenantId);
  });

  it('should handle findUserByEmail for non-existent user', async () => {
    const user = await repo.findUserByEmail('doesnotexist@example.com');
    expect(user).toBeNull();
  });

  it('should handle getTenantMappingForUser for user with no mapping', async () => {
    const email = `test-${uuidv4()}@example.com`;
    const [newUser] = await db.insert(users).values({ email, name: 'No Mapping User' }).returning();
    
    const tenantId = await repo.getTenantMappingForUser(newUser.id);
    expect(tenantId).toBeNull();
  });

  it('should throw IdentityInfrastructureError on DB failure for findUserByEmail', async () => {
    const badDb = { select: () => { throw new Error('DB Error'); } } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.findUserByEmail('test@example.com')).rejects.toThrow('Failed to fetch user by email: DB Error');
  });

  it('should throw IdentityInfrastructureError on DB failure for provision', async () => {
    const badDb = { transaction: () => { throw new Error('DB Error'); } } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.provisionUserAndTenant('test@example.com', 'Test')).rejects.toThrow('Failed to provision user and tenant: DB Error');
  });

  it('should throw IdentityInfrastructureError on DB failure for get mapping', async () => {
    const badDb = { select: () => { throw new Error('DB Error'); } } as unknown as ReturnType<typeof createDbClient>['db'];
    const badRepo = new DrizzleTenantRepository(badDb);

    await expect(badRepo.getTenantMappingForUser('123')).rejects.toThrow('Failed to fetch tenant mapping: DB Error');
  });
});
