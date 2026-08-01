import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { AuthenticateUseCase, IdentityContext } from '@soopa/identity';

@Injectable()
export class TenantAuthGuard implements CanActivate {
  private readonly logger = new Logger(TenantAuthGuard.name);

  constructor(private readonly authenticateUseCase: AuthenticateUseCase) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<
      FastifyRequest & {
        ucpTenantId?: string;
        identityContext?: IdentityContext;
      }
    >();
    const authHeader = request.headers.authorization;

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new UnauthorizedException('Missing or invalid Bearer token');
    }

    const token = authHeader.split(' ')[1];
    const tenantIdParam = (request.params as Record<string, string | string[]>)
      .tenantId;
    const requestedTenantId = Array.isArray(tenantIdParam)
      ? tenantIdParam[0]
      : tenantIdParam;

    if (!requestedTenantId) {
      throw new ForbiddenException('Tenant ID missing in request path');
    }

    try {
      const identityContext = await this.authenticateUseCase.execute(token);
      request.identityContext = identityContext;

      // Pass the internal UCP tenant ID down for other downstream consumers (like proxy controllers)
      request.ucpTenantId = requestedTenantId;

      // PlatformAdmins can access any tenant
      if (identityContext.isPlatformAdmin) {
        return true;
      }

      // Standard users must strictly belong to the requested internal tenant
      if (identityContext.tenantId !== requestedTenantId) {
        throw new ForbiddenException(
          `User does not belong to tenant ${requestedTenantId}`,
        );
      }

      return true;
    } catch (error) {
      if (error instanceof ForbiddenException) {
        throw error;
      }
      this.logger.error('Authentication failed');
      throw new UnauthorizedException('Invalid JWT token');
    }
  }
}
