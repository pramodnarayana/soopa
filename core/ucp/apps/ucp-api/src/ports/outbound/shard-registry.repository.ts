export const SHARD_REGISTRY_REPOSITORY = Symbol('SHARD_REGISTRY_REPOSITORY');

export interface IShardRegistryRepository {
  allocateShard(tenantId: string, appSlug: string): Promise<void>;
  deallocateShard(tenantId: string, appSlug: string): Promise<void>;
}
