import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Inject,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import * as crypto from 'crypto';
import type { Request } from 'express';
import * as jwt from 'jsonwebtoken';
import type { IApiTokenRepository } from '../../../../ports/outbound/api-token.repository.js';
import { API_TOKEN_REPOSITORY } from '../../../../ports/outbound/api-token.repository.js';
import { ZitadelAuthService } from '../auth/zitadel-auth.service.js';

@Injectable()
export class TenantAuthGuard implements CanActivate {
  constructor(
    @Inject(API_TOKEN_REPOSITORY)
    private readonly tokenRepo: IApiTokenRepository,
    private readonly authService: ZitadelAuthService,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<Request>();
    const authHeader = request.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new UnauthorizedException('Missing or invalid Bearer token');
    }

    const token = authHeader.split(' ')[1];
    const tenantIdParam = request.params.tenantId;
    const tenantId = Array.isArray(tenantIdParam) ? tenantIdParam[0] : tenantIdParam;

    if (!tenantId) {
      throw new ForbiddenException('Tenant ID missing in request path');
    }

    // Try decoding as JWT first
    const decodedJwt = jwt.decode(token, { complete: true });

    if (decodedJwt && decodedJwt.header && decodedJwt.header.kid) {
      // It's a JWT. Validate it against Zitadel.
      try {
        const payload = await this.authService.verifyToken(token);

        // Verify the primary organization ID (Tenant) matches
        const userOrgId = payload['urn:zitadel:iam:org:id'] as string | undefined;
        if (userOrgId !== tenantId) {
          throw new ForbiddenException(`User does not belong to tenant ${tenantId}`);
        }

        Object.assign(request, { user: payload });
        return true;
      } catch (err) {
        if (err instanceof ForbiddenException) {
          throw err;
        }
        throw new UnauthorizedException('Invalid JWT token');
      }
    }

    // If it's not a JWT, it must be a UCP API Token using the Split Token Pattern (soopa_live_clientId_rawSecret)
    // token format: soopa_live_[clientId]_[rawSecret]
    if (!token.startsWith('soopa_live_')) {
      throw new UnauthorizedException('Invalid API Token format');
    }

    const lastUnderscoreIndex = token.lastIndexOf('_');
    if (lastUnderscoreIndex <= 11) {
      // 11 is the length of 'soopa_live_'
      throw new UnauthorizedException('Invalid API Token format');
    }

    const rawSecret = token.slice(lastUnderscoreIndex + 1);
    const clientId = token.slice(11, lastUnderscoreIndex);

    if (!clientId || !rawSecret) {
      throw new UnauthorizedException('Invalid API Token format');
    }

    const matchingToken = await this.tokenRepo.findByClientId(tenantId, clientId);

    if (!matchingToken || !matchingToken.active) {
      throw new UnauthorizedException('Invalid API Token');
    }

    const secretHash = crypto.createHash('sha256').update(rawSecret).digest('hex');
    const storedHashBuffer = Buffer.from(matchingToken.secretHash, 'hex');
    const providedHashBuffer = Buffer.from(secretHash, 'hex');

    if (
      storedHashBuffer.length !== providedHashBuffer.length ||
      !crypto.timingSafeEqual(storedHashBuffer, providedHashBuffer)
    ) {
      throw new UnauthorizedException('Invalid API Token');
    }

    // Update lastUsedAt timestamp before assigning to request
    const updatedToken = matchingToken.markAsUsed();
    await this.tokenRepo.save(updatedToken);

    Object.assign(request, { apiToken: updatedToken });
    return true;
  }
}
