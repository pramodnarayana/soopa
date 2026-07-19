import fp from 'fastify-plugin';
import { FastifyPluginAsync, FastifyRequest, FastifyReply } from 'fastify';
import { createDbClient } from '@soopa/database';
import { ZitadelJwksVerifier } from '../adapters/outbound/zitadel/ZitadelJwksVerifier.js';
import { DrizzleTenantRepository } from '../adapters/outbound/database/DrizzleTenantRepository.js';
import { AuthenticateUseCase } from '../application/Authenticate.js';
import type { IdentityContext } from '../domain/IdentityContext.js';
import { TenantMappingDomainError, IdentityInfrastructureError } from '../domain/Errors.js';

export interface IdentityPluginOptions {
  zitadelIssuer: string;
  zitadelAudience: string;
  dbConnectionString: string;
}

declare module 'fastify' {
  interface FastifyRequest {
    identity?: IdentityContext | null;
    tenantId: string;
    userId: string;
  }
  interface FastifyInstance {
    verifyTenant: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }
}

export const identityPlugin: FastifyPluginAsync<IdentityPluginOptions> = async (fastify, options) => {
  const { db } = createDbClient(options.dbConnectionString);
  const tokenVerifier = new ZitadelJwksVerifier({
    issuer: options.zitadelIssuer,
    audience: options.zitadelAudience
  });
  const tenantRepo = new DrizzleTenantRepository(db);
  const authenticateUseCase = new AuthenticateUseCase(tokenVerifier, tenantRepo);

  fastify.decorateRequest('identity', null);
  fastify.decorateRequest('tenantId', '');
  fastify.decorateRequest('userId', '');

  fastify.decorate('verifyTenant', async (request: FastifyRequest, reply: FastifyReply) => {
    const authHeader = request.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      reply.status(401).send({ error: 'Missing or invalid Authorization header' });
      return;
    }

    const token = authHeader.split(' ')[1];

    try {
      const identity = await authenticateUseCase.execute(token);
      
      request.identity = identity;
      request.tenantId = identity.tenantId;
      request.userId = identity.userId;
      
    } catch (err: unknown) {
      request.log.error(err);
      
      if (err instanceof TenantMappingDomainError) {
        reply.status(403).send({ error: 'Forbidden: User is not assigned to a tenant.' });
      } else if (err instanceof IdentityInfrastructureError) {
        reply.status(500).send({ error: 'Internal Server Error: Identity provider failure.' });
      } else {
        reply.status(401).send({ error: 'Invalid authentication credentials' });
      }
    }
  });
};

export default fp(identityPlugin, {
  name: '@soopa/identity'
});
