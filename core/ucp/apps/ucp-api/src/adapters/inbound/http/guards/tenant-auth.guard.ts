import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Inject,
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
import type { ITenantRepository } from '../../../../ports/outbound/tenant.repository.js';
import { TENANT_REPOSITORY } from '../../../../ports/outbound/tenant.repository.js';

@Injectable()
export class TenantAuthGuard implements CanActivate {
  private readonly logger = new Logger(TenantAuthGuard.name);

  constructor(
    private readonly authenticateUseCase: AuthenticateUseCase,
    @Inject(TENANT_REPOSITORY) private readonly tenantRepo: ITenantRepository,
  ) {}

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
    const params = request.params as Record<string, string | string[]>;
    const tenantIdParam = params.tenantId || params.id;
    const requestedTenantId = Array.isArray(tenantIdParam) ? tenantIdParam[0] : tenantIdParam;

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
        // Fallback: check if requestedTenantId is an IdP Tenant ID and resolve to canonical ID
        this.logger.debug(
          `Tenant mismatch. requested: ${requestedTenantId}, context: ${identityContext.tenantId}. Attempting IdP resolution...`,
        );
        const resolvedTenant = await this.tenantRepo.findByIdpTenantId(requestedTenantId);
        if (!resolvedTenant) {
          this.logger.debug(
            `IdP resolution failed. No tenant found for idpTenantId: ${requestedTenantId}`,
          );
          throw new ForbiddenException(`User does not belong to tenant ${requestedTenantId}`);
        }
        if (identityContext.tenantId !== resolvedTenant.id) {
          this.logger.debug(
            `IdP resolution succeeded, but canonical ID mismatch. context: ${identityContext.tenantId}, resolved: ${resolvedTenant.id}`,
          );
          throw new ForbiddenException(`User does not belong to tenant ${requestedTenantId}`);
        }
        // If it matches via IDP, update the request.ucpTenantId to the canonical ID
        request.ucpTenantId = resolvedTenant.id;
      }

      return true;
    } catch (error) {
      // Domain errors — translate to the correct HTTP status
      if (error instanceof ForbiddenException) {
        throw error;
      }
      if (error instanceof MissingUserDomainError) {
        this.logger.warn(`Access denied — user not synced: ${error.message}`);
        throw new ForbiddenException(
          'Your account is still being provisioned. Please try again in a few moments.',
        );
      }
      if (error instanceof TenantMappingDomainError) {
        // User exists but has not been assigned to a tenant by a Platform Admin yet
        this.logger.warn(`Access denied — user has no tenant mapping: ${error.message}`);
        throw new ForbiddenException(
          'User is not assigned to any tenant. Contact your Platform Administrator.',
        );
      }
      if (error instanceof MissingIdentityTenantError) {
        this.logger.warn(`Access denied — token is missing Zitadel org ID: ${error.message}`);
        throw new UnauthorizedException(
          'Token is missing organization context. Please log in again.',
        );
      }

      // Unexpected errors — log the real reason, never swallow it silently
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
