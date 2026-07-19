import { describe, it, expect, vi, beforeEach } from 'vitest';
import Fastify from 'fastify';
import { identityPlugin } from '../src/middleware/fastifyPlugin.js';
import { TenantMappingDomainError, IdentityInfrastructureError } from '../src/domain/Errors.js';

vi.mock('@soopa/database', () => ({
  createDbClient: vi.fn()
}));

vi.mock('../src/adapters/outbound/zitadel/ZitadelJwksVerifier.js', () => ({
  ZitadelJwksVerifier: class { constructor() {} }
}));

vi.mock('../src/adapters/outbound/database/DrizzleTenantRepository.js', () => ({
  DrizzleTenantRepository: class { constructor() {} }
}));

const mockExecute = vi.fn();
vi.mock('../src/application/Authenticate.js', () => ({
  AuthenticateUseCase: class {
    execute = mockExecute;
  }
}));

describe('fastifyPlugin', () => {
  let fastify: ReturnType<typeof Fastify>;

  beforeEach(async () => {
    vi.clearAllMocks();
    fastify = Fastify();
    await fastify.register(identityPlugin, {
      zitadelIssuer: 'https://iss.com',
      zitadelAudience: 'aud',
      dbConnectionString: 'postgres://db'
    });

    fastify.get('/test', { preHandler: [(fastify as any).verifyTenant] }, (req, reply) => {
      reply.send({ userId: req.userId, tenantId: req.tenantId });
    });
  });

  it('should return 401 if authorization header is missing', async () => {
    const response = await fastify.inject({
      method: 'GET',
      url: '/test'
    });

    expect(response.statusCode).toBe(401);
    expect(response.json()).toEqual({ error: 'Missing or invalid Authorization header' });
  });

  it('should return 401 if authorization header is invalid', async () => {
    const response = await fastify.inject({
      method: 'GET',
      url: '/test',
      headers: { authorization: 'Basic token' }
    });

    expect(response.statusCode).toBe(401);
  });

  it('should authenticate user and decorate request', async () => {
    mockExecute.mockResolvedValueOnce({
      userId: 'u1',
      tenantId: 't1',
      email: 'test@test.com',
      name: 'Test',
      roles: []
    });

    const response = await fastify.inject({
      method: 'GET',
      url: '/test',
      headers: { authorization: 'Bearer valid-token' }
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ userId: 'u1', tenantId: 't1' });
    expect(mockExecute).toHaveBeenCalledWith('valid-token');
  });

  it('should return 403 on TenantMappingDomainError', async () => {
    mockExecute.mockRejectedValueOnce(new TenantMappingDomainError('test'));

    const response = await fastify.inject({
      method: 'GET',
      url: '/test',
      headers: { authorization: 'Bearer token' }
    });

    expect(response.statusCode).toBe(403);
  });

  it('should return 500 on IdentityInfrastructureError', async () => {
    mockExecute.mockRejectedValueOnce(new IdentityInfrastructureError('db failed'));

    const response = await fastify.inject({
      method: 'GET',
      url: '/test',
      headers: { authorization: 'Bearer token' }
    });

    expect(response.statusCode).toBe(500);
  });

  it('should return 401 on other errors', async () => {
    mockExecute.mockRejectedValueOnce(new Error('bad jwt'));

    const response = await fastify.inject({
      method: 'GET',
      url: '/test',
      headers: { authorization: 'Bearer token' }
    });

    expect(response.statusCode).toBe(401);
  });
});
