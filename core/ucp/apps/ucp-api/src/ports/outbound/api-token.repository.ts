import { ApiToken } from '../../domain/models/api-token.model.js';

export const API_TOKEN_REPOSITORY = 'API_TOKEN_REPOSITORY';

export interface IApiTokenRepository {
  save(token: ApiToken): Promise<void>;
  findById(tenantId: string, id: string): Promise<ApiToken | null>;
  findAllByTenant(tenantId: string): Promise<ApiToken[]>;
  delete(tenantId: string, id: string): Promise<void>;
}
