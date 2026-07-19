import { CanActivate, ExecutionContext, Injectable, UnauthorizedException, ForbiddenException, InternalServerErrorException, Logger } from '@nestjs/common';
import { Request } from 'express';
import { AuthenticateUseCase } from '../application/Authenticate.js';
import { TenantMappingDomainError, IdentityInfrastructureError } from '../domain/Errors.js';
import type { IdentityContext as Identity } from '../domain/IdentityContext.js';

export interface AuthenticatedRequest extends Request {
  identity: Identity;
  tenantId: string;
  userId: string;
}

@Injectable()
export class AuthGuard implements CanActivate {
  private readonly logger = new Logger(AuthGuard.name);

  constructor(private readonly authenticateUseCase: AuthenticateUseCase) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<AuthenticatedRequest>();
    const authHeader = request.headers['authorization'];

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new UnauthorizedException('Missing or invalid Authorization header');
    }

    const token = authHeader.split(' ')[1];

    try {
      const identity = await this.authenticateUseCase.execute(token);
      
      // Inject into request safely
      request.identity = identity;
      request.tenantId = identity.tenantId;
      request.userId = identity.userId;
      
      return true;
    } catch (err: unknown) {
      if (err instanceof Error) {
        this.logger.error(err.message, err.stack);
      } else {
        const errObj = typeof err === 'string' ? err : 'Unknown error object';
        this.logger.error(`Unknown error occurred during authentication: ${errObj}`);
      }

      if (err instanceof TenantMappingDomainError) {
        throw new ForbiddenException('User is not assigned to a tenant.');
      } else if (err instanceof IdentityInfrastructureError) {
        throw new InternalServerErrorException('An internal identity error occurred.');
      }
      
      throw new UnauthorizedException('Invalid or expired token.');
    }
  }
}
