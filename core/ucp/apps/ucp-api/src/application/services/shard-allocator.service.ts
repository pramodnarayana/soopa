import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import {
  type IShardRegistryRepository,
  SHARD_REGISTRY_REPOSITORY,
} from '../../ports/outbound/shard-registry.repository.js';

@Injectable()
export class ShardAllocatorService {
  private readonly logger = new Logger(ShardAllocatorService.name);

  constructor(
    @Inject(SHARD_REGISTRY_REPOSITORY)
    private readonly shardRegistryRepo: IShardRegistryRepository,
  ) {}

  @OnEvent('app.subscribed')
  async allocateShard(event: { payload: { tenantId: string; appSlug: string } }): Promise<void> {
    const {
      payload: { tenantId, appSlug },
    } = event;

    await this.shardRegistryRepo.allocateShard(tenantId, appSlug);
  }

  @OnEvent('app.unsubscribed')
  async deallocateShard(event: { payload: { tenantId: string; appSlug: string } }): Promise<void> {
    const {
      payload: { tenantId, appSlug },
    } = event;

    await this.shardRegistryRepo.deallocateShard(tenantId, appSlug);
  }
}
