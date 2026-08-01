import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { appSubscriptions, apps, SubscriptionStatus } from '@soopa/database';
import { and, eq } from 'drizzle-orm';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import { IAppSubscriptionRepository } from '../../../ports/outbound/app-subscription.repository.js';

@Injectable()
export class AppSubscriptionDrizzleRepository implements IAppSubscriptionRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  async getActiveAppSlugsForTenant(tenantId: string): Promise<string[]> {
    const subscriptions = await this.db
      .select({
        appSlug: apps.slug,
      })
      .from(appSubscriptions)
      .innerJoin(apps, eq(apps.id, appSubscriptions.appId))
      .where(
        and(
          eq(appSubscriptions.tenantId, tenantId),
          eq(appSubscriptions.status, SubscriptionStatus.ACTIVE),
        ),
      );

    return subscriptions.map((s) => s.appSlug);
  }
}
