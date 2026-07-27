import { describe, expect, it } from 'vitest';
import { AuthenticateUseCase } from '../src/application/Authenticate.js';
import { TenantMappingDomainError } from '../src/domain/Errors.js';
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
  public users: Record<string, { id: string; name: string; email?: string }> = {};
  public mappings: Record<string, string> = {};
  public provisioned: { userId: string; tenantId: string } | null = null;

  async findUserByEmail(email: string): Promise<UserData | null> {
    return (this.users[email] as UserData) || null;
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
    verifier.claims = { sub: 'new-user', email: 'test@example.com', name: 'Test User' };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u1', tenantId: 't1' };

    const useCase = new AuthenticateUseCase(verifier, repo);
    const result = await useCase.execute('valid');

    expect(result).toEqual({
      userId: 'u1',
      tenantId: 't1',
      email: 'test@example.com',
      name: 'Test User',
      roles: ['admin'],
    });
  });

  it('should return existing user and tenant if they exist', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'existing-user',
      email: 'existing@example.com',
      name: 'Existing User',
    };

    const repo = new FakeTenantRepository();
    repo.users['existing@example.com'] = { id: 'u2', name: 'Existing User DB' };
    repo.mappings['u2'] = 't2';

    const useCase = new AuthenticateUseCase(verifier, repo);
    const result = await useCase.execute('valid');

    expect(result).toEqual({
      userId: 'u2',
      tenantId: 't2',
      email: 'existing@example.com',
      name: 'Existing User DB',
      roles: ['admin'],
    });
  });

  it('should throw TenantMappingDomainError if user exists but has no tenant mapping', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = {
      sub: 'existing-user',
      email: 'no-tenant@example.com',
      name: 'Existing User',
    };

    const repo = new FakeTenantRepository();
    repo.users['no-tenant@example.com'] = { id: 'u3', name: 'User 3' };
    // No mapping set

    const useCase = new AuthenticateUseCase(verifier, repo);
    await expect(useCase.execute('valid')).rejects.toThrow(TenantMappingDomainError);
  });

  it('should fall back to sub if email is missing', async () => {
    const verifier = new FakeTokenVerifier();
    verifier.claims = { sub: 'fallback-sub' };

    const repo = new FakeTenantRepository();
    repo.provisioned = { userId: 'u4', tenantId: 't4' };

    const useCase = new AuthenticateUseCase(verifier, repo);
    const result = await useCase.execute('valid');

    expect(result.email).toBe('fallback-sub');
    expect(result.name).toBe('fallback-sub');
  });
});
