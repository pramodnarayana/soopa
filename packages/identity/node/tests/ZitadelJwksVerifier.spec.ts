import { describe, it, expect, vi } from 'vitest';
import { ZitadelJwksVerifier } from '../src/adapters/outbound/zitadel/ZitadelJwksVerifier.js';
import * as jose from 'jose';

vi.mock('jose', () => ({
  createRemoteJWKSet: vi.fn().mockReturnValue(vi.fn().mockResolvedValue('test-key')),
  jwtVerify: vi.fn()
}));

describe('ZitadelJwksVerifier', () => {
  it('should verify token using jose', async () => {
    const verifier = new ZitadelJwksVerifier({ issuer: 'https://iss.com', audience: 'aud' });
    
    vi.mocked(jose.jwtVerify).mockResolvedValue({
      payload: { sub: 'test-user', email: 'test@test.com' }
    });

    const claims = await verifier.verify('token');
    
    expect(claims.sub).toBe('test-user');
    expect(jose.createRemoteJWKSet).toHaveBeenCalledWith(expect.any(URL));
    expect(jose.jwtVerify).toHaveBeenCalledWith('token', expect.any(Function), {
      issuer: 'https://iss.com',
      audience: 'aud'
    });
  });
});
