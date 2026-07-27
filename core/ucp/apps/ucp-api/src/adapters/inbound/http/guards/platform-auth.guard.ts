import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Request } from 'express';
import { ZitadelAuthService } from '../auth/zitadel-auth.service.js';

@Injectable()
export class PlatformAuthGuard implements CanActivate {
  constructor(
    private readonly authService: ZitadelAuthService,
    private readonly configService: ConfigService,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<Request>();
    const authHeader = request.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.error('PlatformAuthGuard: Missing or invalid Bearer token');
      throw new UnauthorizedException('Missing or invalid Bearer token');
    }

    const token = authHeader.split(' ')[1];

    const payload = await this.authService.verifyToken(token);
    const audience = this.configService.get<string>('ZITADEL_UCP_PROJECT_ID');

    // Verify the user has PlatformAdmin role
    const defaultRoles = payload['urn:zitadel:iam:org:project:roles'] as
      | Record<string, unknown>
      | undefined;
    const ucpRoles = payload[`urn:zitadel:iam:org:project:id:${audience}:roles`] as
      | Record<string, unknown>
      | undefined;

    const hasPlatformAdminInDefault = defaultRoles && 'PlatformAdmin' in defaultRoles;
    const hasPlatformAdminInUcp = ucpRoles && 'PlatformAdmin' in ucpRoles;

    if (!hasPlatformAdminInDefault && !hasPlatformAdminInUcp) {
      console.error('PlatformAuthGuard: User missing PlatformAdmin role');
      throw new ForbiddenException('User is not a Platform Administrator');
    }

    console.log('PlatformAuthGuard: Success!');
    Object.assign(request, { user: payload });
    return true;
  }
}
