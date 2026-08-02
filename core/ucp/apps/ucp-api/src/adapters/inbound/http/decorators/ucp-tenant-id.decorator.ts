import {
  createParamDecorator,
  ExecutionContext,
  InternalServerErrorException,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

export const UcpTenantId = createParamDecorator((data: unknown, ctx: ExecutionContext): string => {
  const request = ctx.switchToHttp().getRequest<FastifyRequest & { ucpTenantId?: string }>();
  const tenantId = request.ucpTenantId;

  if (!tenantId) {
    // If this decorator is used on a route that is NOT protected by TenantAuthGuard,
    // it is a developer error and should be surfaced immediately.
    throw new InternalServerErrorException(
      'UcpTenantId decorator used on a route without ucpTenantId in request. Did you forget @UseGuards(TenantAuthGuard)?',
    );
  }

  return tenantId;
});
