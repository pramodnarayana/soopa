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
        throw new ForbiddenException('User is not a Platform Administrator');
      }

      return true;
    } catch (error) {
      if (error instanceof ForbiddenException) {
        throw error;
      }
      this.logger.error('Authentication failed', error);
      throw new UnauthorizedException('Invalid JWT token');
    }
  }
}
