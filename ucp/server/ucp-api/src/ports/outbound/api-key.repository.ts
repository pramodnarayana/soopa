import { ApiKey } from '../../domain/models/api-key.model';

export const API_KEY_REPOSITORY = Symbol('API_KEY_REPOSITORY');

export interface IApiKeyRepository {
  findByKeyHash(keyHash: string): Promise<ApiKey | null>;
  findByTenantId(tenantId: string): Promise<ApiKey[]>;
  save(apiKey: ApiKey): Promise<ApiKey>;
  delete(id: string): Promise<void>;
}
