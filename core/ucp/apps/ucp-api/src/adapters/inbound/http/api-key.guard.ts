import {
  CanActivate,
  ExecutionContext,
  Inject,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { ApiKey } from '../../../domain/models/api-key.model.js';
import type { IApiKeyRepository } from '../../../ports/outbound/api-key.repository.js';
import { API_KEY_REPOSITORY } from '../../../ports/outbound/api-key.repository.js';

@Injectable()
export class ApiKeyGuard implements CanActivate {
  constructor(
    @Inject(API_KEY_REPOSITORY) private readonly apiKeyRepo: IApiKeyRepository,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context
      .switchToHttp()
      .getRequest<FastifyRequest & { apiKey?: ApiKey }>();
    const authHeader = request.headers.authorization;

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new UnauthorizedException(
        'Missing or invalid Authorization header',
      );
    }

    const rawSecret = authHeader.substring(7).trim();
    const keyHash = ApiKey.hashSecret(rawSecret);

    const apiKey = await this.apiKeyRepo.findByKeyHash(keyHash);
    if (!apiKey) {
      throw new UnauthorizedException('Invalid API Key');
    }

    // Attach API key context to the request for controllers to use
    request.apiKey = apiKey;
    return true;
  }
}
