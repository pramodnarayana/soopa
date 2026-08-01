import { createParamDecorator, ExecutionContext } from '@nestjs/common';
import type { IdentityContext } from '@soopa/identity';
import type { FastifyRequest } from 'fastify';

export const Identity = createParamDecorator(
  (data: unknown, ctx: ExecutionContext): IdentityContext => {
    const request = ctx
      .switchToHttp()
      .getRequest<FastifyRequest & { identityContext?: IdentityContext }>();
    if (!request.identityContext) {
      throw new Error(
        'IdentityContext not found on request. Did you forget to apply a TenantAuthGuard or PlatformAuthGuard?',
      );
    }
    return request.identityContext;
  },
);
