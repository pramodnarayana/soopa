import type { ApiToken, ApiTokenCreated, CreateApiTokenPayload } from '../types';

export interface IApiTokenRepository {
  getApiTokens(): Promise<{ tokens: ApiToken[] }>;
  createApiToken(payload: CreateApiTokenPayload): Promise<ApiTokenCreated>;
  revokeApiToken(id: string): Promise<void>;
  deleteApiToken(id: string): Promise<void>;
}
