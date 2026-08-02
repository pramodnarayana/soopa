import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import {
  AuthenticateUseCase,
  IdentityContext,
  MissingIdentityTenantError,
  MissingUserDomainError,
  TenantMappingDomainError,
} from '@soopa/identity';
import type { FastifyRequest } from 'fastify';

@Injectable()
export class PlatformAuthGuard implements CanActivate {
  private readonly logger = new Logger(PlatformAuthGuard.name);

  constructor(private readonly authenticateUseCase: AuthenticateUseCase) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context
      .switchToHttp()
      .getRequest<FastifyRequest & { identityContext?: IdentityContext }>();
    const authHeader = request.headers.authorization;

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new UnauthorizedException('Missing or invalid Bearer token');
    }

    const token = authHeader.split(' ')[1];

    try {
      const identityContext = await this.authenticateUseCase.execute(token);
      request.identityContext = identityContext;

      if (!identityContext.isPlatformAdmin) {
        throw new ForbiddenException('Platform Administrator privileges required');
      }

      return true;
    } catch (error) {
      if (error instanceof ForbiddenException) {
        throw error;
      }
      if (error instanceof MissingUserDomainError) {
        this.logger.warn(`Platform access denied — user not synced: ${error.message}`);
        throw new ForbiddenException(
          'Your account is still being provisioned. Please try again in a few moments.',
        );
      }
      if (error instanceof TenantMappingDomainError) {
        this.logger.warn(`Platform access denied — user has no tenant mapping: ${error.message}`);
        throw new ForbiddenException('User is not assigned to any tenant.');
      }
      if (error instanceof MissingIdentityTenantError) {
        this.logger.warn(`Platform access denied — token missing org context: ${error.message}`);
        throw new UnauthorizedException(
          'Token is missing organization context. Please log in again.',
        );
      }

      // Log the real error — never swallow silently
      if (error instanceof Error) {
        this.logger.error(
          `Authentication failed: [${error.constructor.name}] ${error.message}`,
          error.stack,
        );
      } else {
        this.logger.error(`Authentication failed (unknown error type):`, error);
      }
      throw new UnauthorizedException('Invalid JWT token');
    }
  }
}
