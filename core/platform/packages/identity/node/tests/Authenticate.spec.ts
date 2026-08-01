import { describe, expect, it } from 'vitest';
import { AuthenticateUseCase } from '../src/application/Authenticate.js';
import { MissingIdentityTenantError, TenantMappingDomainError } from '../src/domain/Errors.js';
import type { TokenClaims } from '../src/domain/IdentityContext.js';
import type { TenantRepository, UserData } from '../src/ports/TenantRepository.js';
import type { TokenVerifier } from '../src/ports/TokenVerifier.js';

// Fake implementations instead of magic mocks
class FakeTokenVerifier implements TokenVerifier {
  public claims: Record<string, unknown> = {};
  public async verify(token: string): Promise<TokenClaims> {
    if (token === 'bad') throw new Error('Invalid token');
    return this.claims as unknown as TokenClaims;
  }
}

class FakeTenantRepository implements TenantRepository {
  public users: Record<string, UserData> = {};
  public mappings: Record<string, string> = {};
  public provisioned: { userId: string; tenantId: string } | null = null;

  async findUserByEmail(email: string): Promise<UserData | null> {
    return this.users[email] ?? null;
  }

  async provisionUserAndTenant(_email: string, _name: string, _zitadelOrgId?: string) {
    if (!this.provisioned) throw new Error('provisioned stub not set');
    return this.provisioned;
  }

  async getTenantMappingForUser(userId: string) {
    return this.mappings[userId] || null;
  }
}

describe('AuthenticateUseCase', () => {
  it('should provision a new user and tenant if user does not exist', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = { sub: 'new-user', email: 'test@example.com', name: 'Test User', tenant_id: 'org123' };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u1', tenantId: 't1' };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result).toEqual({
      userId: 'u1',
      tenantId: 't1',
      email: 'test@example.com',
      name: 'Test User',
      roles: [],
      rawRoles: [],
      isPlatformAdmin: false,
    });
  });

  it('should return existing user and tenant if they exist', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'existing-user',
      email: 'existing@example.com',
      name: 'Existing User',
      tenant_id: 'org123',
    };

    const repo = new FakeTenantRepository();
    repo.users['existing@example.com'] = {
      id: 'u2',
      name: 'Existing User DB',
      email: 'existing@example.com',
    } satisfies UserData;
    repo.mappings['u2'] = 't2';

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result).toEqual({
      userId: 'u2',
      tenantId: 't2',
      email: 'existing@example.com',
      name: 'Existing User DB',
      roles: [],
      rawRoles: [],
      isPlatformAdmin: false,
    });
  });

  it('should throw TenantMappingDomainError if user exists but has no tenant mapping', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'existing-user',
      email: 'no-tenant@example.com',
      name: 'Existing User',
      tenant_id: 'org123',
    };

    const repo = new FakeTenantRepository();
    repo.users['no-tenant@example.com'] = {
      id: 'u3',
      name: 'User 3',
      email: 'no-tenant@example.com',
    } satisfies UserData;
    // No mapping set

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    await expect(useCase.execute('valid')).rejects.toThrow(TenantMappingDomainError);
  });

  it('should fall back to sub if email is missing', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = { sub: 'fallback-sub', tenant_id: 'org123' };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u4', tenantId: 't4' };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result.email).toBe('fallback-sub');
    expect(result.name).toBe('fallback-sub');
  });

  it('should detect PlatformAdmin from urn:zitadel:iam:org:project:roles', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'admin-user',
      email: 'admin@example.com',
      name: 'Admin User',
      tenant_id: 'org123',
      'urn:zitadel:iam:org:project:roles': { PlatformAdmin: {} },
    };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u5', tenantId: 't5' };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result.isPlatformAdmin).toBe(true);
    expect(result.roles).toContain('PlatformAdmin');
    expect(result.rawRoles).toContain('PlatformAdmin');
  });

  it('should detect PlatformAdmin from audience-scoped roles', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'admin-user-2',
      email: 'admin2@example.com',
      name: 'Admin User 2',
      tenant_id: 'org456',
      'urn:zitadel:iam:org:project:id:test-audience:roles': { PlatformAdmin: {}, OtherRole: {} },
    };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u6', tenantId: 't6' };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result.isPlatformAdmin).toBe(true);
    expect(result.roles).toContain('PlatformAdmin');
    expect(result.rawRoles).toContain('PlatformAdmin');
    expect(result.rawRoles).toContain('OtherRole');
  });

  it('should throw MissingIdentityTenantError when organization ID and tenant_id are both missing', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'no-org-user',
      email: 'noorg@example.com',
      name: 'No Org User',
    };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u7', tenantId: 't7' };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });

    await expect(useCase.execute('valid')).rejects.toThrow(MissingIdentityTenantError);
    await expect(useCase.execute('valid')).rejects.toThrow('Missing Zitadel Organization ID for user noorg@example.com');
  });

  it('should not provision user when missing tenant information', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'no-tenant-data',
      email: 'notenantdata@example.com',
    };

    const repo = new FakeTenantRepository();
    let provisionCalled = false;
    repo.provisionUserAndTenant = async () => {
      provisionCalled = true;
      return { userId: 'should-not-be-called', tenantId: 'should-not-be-called' };
    };

    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });

    await expect(useCase.execute('valid')).rejects.toThrow(MissingIdentityTenantError);
    expect(provisionCalled).toBe(false);
  });
});
