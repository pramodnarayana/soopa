import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import type { Request } from 'express';
import { ZitadelAuthService } from '../auth/zitadel-auth.service.js';

@Injectable()
export class PlatformAuthGuard implements CanActivate {
  constructor(private readonly authService: ZitadelAuthService) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<Request>();
    const authHeader = request.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.error('PlatformAuthGuard: Missing or invalid Bearer token. authHeader:', authHeader);
      throw new UnauthorizedException('Missing or invalid Bearer token');
    }

    const token = authHeader.split(' ')[1];

    const payload = await this.authService.verifyToken(token);

    // Verify the user has PlatformAdmin role
    console.log('JWT Payload:', JSON.stringify(payload, null, 2));
    const defaultRoles = payload['urn:zitadel:iam:org:project:roles'] as
      | Record<string, unknown>
      | undefined;
    const ucpRoles = payload[
      `urn:zitadel:iam:org:project:id:${process.env.ZITADEL_UCP_PROJECT_ID}:roles`
    ] as Record<string, unknown> | undefined;

    const roles = defaultRoles || ucpRoles;
    if (!roles || !('PlatformAdmin' in roles)) {
      console.error('PlatformAuthGuard: User missing PlatformAdmin role. Roles:', roles);
      throw new ForbiddenException('User is not a Platform Administrator');
    }

    console.log('PlatformAuthGuard: Success!');
    Object.assign(request, { user: payload });
    return true;
  }
}
