import { describe, expect, it } from 'vitest';
import { AuthenticateUseCase } from '../src/application/Authenticate.js';
import {
  MissingIdentityTenantError,
  MissingUserDomainError,
  TenantMappingDomainError,
} from '../src/domain/Errors.js';
import type { TokenClaims } from '../src/domain/IdentityContext.js';
import type { TenantRepository, UserData } from '../src/ports/TenantRepository.js';
import type { TokenVerifier } from '../src/ports/TokenVerifier.js';

// Fake implementations — no mocks
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

  async findUserByEmail(email: string): Promise<UserData | null> {
    return this.users[email] ?? null;
  }

  async findUserByIdpId(idpUserId: string): Promise<UserData | null> {
    return this.users[idpUserId] ?? null;
  }

  async getTenantMappingForUser(userId: string): Promise<string | null> {
    return this.mappings[userId] || null;
  }
}

describe('AuthenticateUseCase', () => {
  it('should throw MissingUserDomainError if user is not synced (no JIT)', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'new-user',
      email: 'new@example.com',
      name: 'New User',
      tenant_id: 'org123',
    };

    const repo = new FakeTenantRepository();
    // No user in DB -> MissingUserDomainError
    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });

    await expect(useCase.execute('valid')).rejects.toThrow(MissingUserDomainError);
  });

  it('should return context if user exists and has a tenant mapping', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'existing-user',
      email: 'existing@example.com',
      name: 'Existing User',
      tenant_id: 'org123',
    };

    const repo = new FakeTenantRepository();
    repo.users['existing-user'] = {
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
    repo.users['existing-user'] = {
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
    repo.users['fallback-sub'] = {
      id: 'u4',
      name: 'User 4',
      email: 'fallback-sub',
    } satisfies UserData;

    // PlatformAdmin — allowed with empty tenantId
    const useCase = new AuthenticateUseCase(verifier, repo, {
      audience: 'test-audience',
    });

    // Will throw TenantMappingDomainError since no tenant and not a platform admin
    await expect(useCase.execute('valid')).rejects.toThrow(TenantMappingDomainError);
  });

  it('PlatformAdmin should authenticate even without a tenant mapping', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'admin-user',
      email: 'admin@example.com',
      name: 'Admin User',
      tenant_id: 'org123',
      'urn:zitadel:iam:org:project:roles': { PlatformAdmin: {} },
    };

    const repo = new FakeTenantRepository();
    repo.users['admin-user'] = {
      id: 'u5',
      name: 'Admin User',
      email: 'admin@example.com',
    } satisfies UserData;

    // No tenant mapping — platform admin bypasses the check
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
    repo.users['admin-user-2'] = {
      id: 'u6',
      name: 'Admin User 2',
      email: 'admin2@example.com',
    } satisfies UserData;

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
    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });

    await expect(useCase.execute('valid')).rejects.toThrow(MissingIdentityTenantError);
    await expect(useCase.execute('valid')).rejects.toThrow('Missing Zitadel Organization ID');
  });

  it('should resolve organization ID from role claims when tenant_id is missing', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'role-org-user',
      email: 'roleorg@example.com',
      name: 'Role Org User',
      'urn:zitadel:iam:org:project:roles': { PlatformAdmin: { org789: 'example.com' } },
    };

    const repo = new FakeTenantRepository();
    repo.users['role-org-user'] = {
      id: 'u7',
      name: 'Role Org User',
      email: 'roleorg@example.com',
    } satisfies UserData;

    // PlatformAdmin bypasses tenant check
    const useCase = new AuthenticateUseCase(verifier, repo, { audience: 'test-audience' });
    const result = await useCase.execute('valid');

    expect(result.isPlatformAdmin).toBe(true);
    expect(result.userId).toBe('u7');
    expect(result.tenantId).toBe('');
  });
});
