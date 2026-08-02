import { ApiKey } from '../../domain/models/api-key.model.js';

export const API_KEY_REPOSITORY = Symbol('API_KEY_REPOSITORY');

export interface IApiKeyRepository {
  findByKeyHash(keyHash: string): Promise<ApiKey | null>;
  findByTenantId(tenantId: string): Promise<ApiKey[]>;
  save(apiKey: ApiKey, idempotencyKey?: string): Promise<ApiKey>;
  delete(id: string, idempotencyKey?: string): Promise<void>;
}
