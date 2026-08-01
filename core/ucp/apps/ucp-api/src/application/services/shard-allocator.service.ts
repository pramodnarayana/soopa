import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import type { DbTransaction } from '@soopa/database';
import { apps, databaseShards, shardRegistry } from '@soopa/database';
import { and, asc, eq } from 'drizzle-orm';

@Injectable()
export class ShardAllocatorService {
  private readonly logger = new Logger(ShardAllocatorService.name);

  @OnEvent('app.subscribed')
  async allocateShard(event: {
    payload: { tenantId: string; appSlug: string };
    tx: DbTransaction;
  }): Promise<void> {
    const {
      payload: { tenantId, appSlug },
      tx,
    } = event;
    // 1. Resolve App ID
    const [app] = await tx.select().from(apps).where(eq(apps.slug, appSlug));
    if (!app) {
      throw new Error(`App with slug ${appSlug} not found`);
    }

    // 2. Find a database shard.
    const [shard] = await tx.select().from(databaseShards).orderBy(asc(databaseShards.id)).limit(1);
    if (!shard) {
      throw new Error('No database shards available for allocation');
    }

    // 3. Register or update the tenant in the shard
    await tx
      .insert(shardRegistry)
      .values({
        tenantId,
        appId: app.id,
        shardId: shard.id,
        status: 'active',
      })
      .onConflictDoUpdate({
        target: [shardRegistry.tenantId, shardRegistry.appId],
        set: { status: 'active', shardId: shard.id },
      });
    this.logger.log(
      `Successfully allocated shard ${shard.id} to tenant ${tenantId} for app ${appSlug}`,
    );
  }

  @OnEvent('app.unsubscribed')
  async deactivateShard(event: {
    payload: { tenantId: string; appSlug: string };
    tx: DbTransaction;
  }): Promise<void> {
    const {
      payload: { tenantId, appSlug },
      tx,
    } = event;
    // 1. Resolve App ID
    const [app] = await tx.select().from(apps).where(eq(apps.slug, appSlug));
    if (!app) {
      throw new Error(`App with slug ${appSlug} not found`);
    }

    await tx
      .update(shardRegistry)
      .set({ status: 'inactive' })
      .where(and(eq(shardRegistry.tenantId, tenantId), eq(shardRegistry.appId, app.id)));
    this.logger.log(`Soft deactivated allocation for tenant ${tenantId} for app ${appSlug}`);
  }
}
