import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { apps, databaseShards, shardRegistry } from '@soopa/database';
import { and, asc, eq } from 'drizzle-orm';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import type { IShardRegistryRepository } from '../../../ports/outbound/shard-registry.repository.js';

@Injectable()
export class ShardRegistryDrizzleRepository implements IShardRegistryRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  async allocateShard(tenantId: string, appSlug: string): Promise<void> {
    // 1. Resolve App ID
    const [app] = await this.db.select().from(apps).where(eq(apps.slug, appSlug));
    if (!app) {
      throw new Error(`App with slug ${appSlug} not found`);
    }

    // 2. Find a database shard.
    const [shard] = await this.db
      .select()
      .from(databaseShards)
      .orderBy(asc(databaseShards.id))
      .limit(1);
    if (!shard) {
      throw new Error('No database shards available for allocation');
    }

    // 3. Register or update the tenant in the shard
    await this.db
      .insert(shardRegistry)
      .values({
        tenantId,
        appId: app.id,
        shardId: shard.id,
        status: 'active',
      })
      .onConflictDoUpdate({
        target: [shardRegistry.tenantId, shardRegistry.appId],
        set: { status: 'active' },
      });
  }

  async deallocateShard(tenantId: string, appSlug: string): Promise<void> {
    // 1. Resolve App ID
    const [app] = await this.db.select().from(apps).where(eq(apps.slug, appSlug));
    if (!app) {
      throw new Error(`App with slug ${appSlug} not found`);
    }

    // 2. Mark the shard registration as inactive
    await this.db
      .update(shardRegistry)
      .set({ status: 'inactive' })
      .where(and(eq(shardRegistry.tenantId, tenantId), eq(shardRegistry.appId, app.id)));
  }
}
