import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Inject,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import * as crypto from 'crypto';
import type { Request } from 'express';
import * as jwt from 'jsonwebtoken';
import jwksClient from 'jwks-rsa';
import type { IApiTokenRepository } from '../../../../ports/outbound/api-token.repository.js';
import { API_TOKEN_REPOSITORY } from '../../../../ports/outbound/api-token.repository.js';

@Injectable()
export class TenantAuthGuard implements CanActivate {
  private jwksClient: jwksClient.JwksClient;

  constructor(
    @Inject(API_TOKEN_REPOSITORY)
    private readonly tokenRepo: IApiTokenRepository,
    private readonly configService: ConfigService,
  ) {
    const zitadelUrl = this.configService.get<string>('ZITADEL_URL', 'http://localhost:8080');
    this.jwksClient = jwksClient({
      jwksUri: `${zitadelUrl}/oauth/v2/keys`,
      cache: true,
      rateLimit: true,
    });
  }

  private getKey(header: jwt.JwtHeader, callback: jwt.SigningKeyCallback) {
    this.jwksClient.getSigningKey(header.kid, (err, key) => {
      if (err) return callback(err);
      if (key) {
        const signingKey = key.getPublicKey();
        callback(null, signingKey);
      } else {
        callback(new Error('Key not found'));
      }
    });
  }

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
      return new Promise<boolean>((resolve, reject) => {
        jwt.verify(
          token,
          this.getKey.bind(this),
          {},
          (err, payload: jwt.JwtPayload | string | undefined) => {
            if (err || !payload || typeof payload === 'string') {
              reject(new UnauthorizedException('Invalid JWT token'));
              return;
            }

            // Verify the primary organization ID (Tenant) matches
            const userOrgId = payload['urn:zitadel:iam:org:id'] as string | undefined;
            if (userOrgId !== tenantId) {
              reject(new ForbiddenException(`User does not belong to tenant ${tenantId}`));
              return;
            }

            Object.assign(request, { user: payload });
            resolve(true);
          },
        );
      });
    }

    // If it's not a JWT, it must be a UCP API Token
    const secretHash = crypto.createHash('sha256').update(token).digest('hex');
    const apiTokens = await this.tokenRepo.findAllByTenant(tenantId);

    let matchingToken = null;
    for (const t of apiTokens) {
      if (!t.active) continue;

      // Use timing-safe comparison for secret hash
      const storedHashBuffer = Buffer.from(t.secretHash, 'hex');
      const providedHashBuffer = Buffer.from(secretHash, 'hex');

      // Only compare if lengths match
      if (storedHashBuffer.length === providedHashBuffer.length) {
        if (crypto.timingSafeEqual(storedHashBuffer, providedHashBuffer)) {
          matchingToken = t;
          break;
        }
      }
    }

    if (!matchingToken) {
      throw new UnauthorizedException('Invalid API Token');
    }

    // Update lastUsedAt timestamp before assigning to request
    const updatedToken = matchingToken.markAsUsed();
    await this.tokenRepo.save(updatedToken);

    Object.assign(request, { apiToken: updatedToken });
    return true;
  }
}
