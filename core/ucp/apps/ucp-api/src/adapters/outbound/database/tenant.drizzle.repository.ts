import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import {
  apiKeys,
  appSubscriptions,
  apps,
  controlPlaneOutbox,
  eq,
  generateId,
  shardRegistry,
  tenants,
  tenantUsers,
} from '@soopa/database';
import { and, inArray, sql } from 'drizzle-orm';
import { Tenant } from '../../../domain/models/tenant.model.js';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import { ITenantRepository } from '../../../ports/outbound/tenant.repository.js';

@Injectable()
export class TenantDrizzleRepository implements ITenantRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private mapToDomain(row: typeof tenants.$inferSelect, subscriptions: string[] = []): Tenant {
    return new Tenant(
      row.id,
      row.name,
      row.idpTenantId,
      row.status,
      row.createdAt,
      row.updatedAt,
      subscriptions,
    );
  }

  async findById(id: string): Promise<Tenant | null> {
    const [row] = await this.db.select().from(tenants).where(eq(tenants.id, id));

    if (!row) return null;

    const slugs = await this.loadSubscriptionSlugs(row.id);

    return this.mapToDomain(row, slugs);
  }

  async findByIdpTenantId(idpTenantId: string): Promise<Tenant | null> {
    const [row] = await this.db.select().from(tenants).where(eq(tenants.idpTenantId, idpTenantId));

    if (!row) return null;

    const slugs = await this.loadSubscriptionSlugs(row.id);

    return this.mapToDomain(row, slugs);
  }

  async findAll(): Promise<Tenant[]> {
    const rows = await this.db.select().from(tenants);
    if (rows.length === 0) return [];

    const tenantIds = rows.map((r) => r.id);

    // Batch fetch subscriptions to avoid N+1 anti-pattern
    const subsRows = await this.db
      .select({ tenantId: appSubscriptions.tenantId, slug: apps.slug })
      .from(appSubscriptions)
      .innerJoin(apps, eq(appSubscriptions.appId, apps.id))
      .where(inArray(appSubscriptions.tenantId, tenantIds));

    // Group subscriptions by tenant in memory
    const subsMap = new Map<string, string[]>();
    for (const sub of subsRows) {
      if (!subsMap.has(sub.tenantId)) {
        subsMap.set(sub.tenantId, []);
      }
      subsMap.get(sub.tenantId)!.push(sub.slug);
    }

    return rows.map((row) => this.mapToDomain(row, subsMap.get(row.id) || []));
  }

  async save(tenant: Tenant, idempotencyKey?: string): Promise<Tenant> {
    const resultRow = await this.db.transaction(async (tx) => {
      // 1. Save Tenant
      const [row] = await tx
        .insert(tenants)
        .values({
          id: tenant.id,
          name: tenant.name,
          idpTenantId: tenant.idpTenantId,
          status: tenant.status,
          createdAt: tenant.createdAt,
          updatedAt: tenant.updatedAt,
        })
        .onConflictDoUpdate({
          target: tenants.id,
          set: {
            name: tenant.name,
            idpTenantId: tenant.idpTenantId,
            status: tenant.status,
            updatedAt: new Date(),
          },
        })
        .returning();

      // 2. Save Subscriptions (Enterprise Grade Symmetric Diff)
      // Fetch current subscriptions from the DB
      const existingSubsRows = await tx
        .select({ appId: appSubscriptions.appId, slug: apps.slug })
        .from(appSubscriptions)
        .innerJoin(apps, eq(appSubscriptions.appId, apps.id))
        .where(eq(appSubscriptions.tenantId, tenant.id));

      const existingSlugs = new Set(existingSubsRows.map((r) => r.slug));
      const targetSlugs = new Set(tenant.subscriptions || []);

      // Calculate diffs
      const slugsToAdd = [...targetSlugs].filter((slug) => !existingSlugs.has(slug));
      const slugsToRemove = [...existingSlugs].filter((slug) => !targetSlugs.has(slug));

      // Execute precise deletions
      if (slugsToRemove.length > 0) {
        const appsToRemove = existingSubsRows
          .filter((r) => slugsToRemove.includes(r.slug))
          .map((r) => r.appId);
        await tx
          .delete(appSubscriptions)
          .where(
            and(
              eq(appSubscriptions.tenantId, tenant.id),
              inArray(appSubscriptions.appId, appsToRemove),
            ),
          );
      }

      // Execute precise insertions
      if (slugsToAdd.length > 0) {
        const dbAppsToAdd = await tx.select().from(apps).where(inArray(apps.slug, slugsToAdd));
        if (dbAppsToAdd.length > 0) {
          const subs = dbAppsToAdd.map((app) => ({
            tenantId: tenant.id,
            appId: app.id,
            tier: 'standard',
          }));
          await tx.insert(appSubscriptions).values(subs).onConflictDoNothing();
        }
      }

      // 3. Process Outbox Events (Domain Events)
      let index = 0;
      for (const event of tenant.domainEvents) {
        const outboxId = generateId('evt');
        const finalIdempotencyKey = idempotencyKey
          ? `${idempotencyKey}_${index}`
          : `${event.eventName}_${tenant.id}_${event.occurredOn.getTime()}`;

        await tx.insert(controlPlaneOutbox).values({
          id: outboxId,
          idempotencyKey: finalIdempotencyKey,
          tenantId: tenant.id,
          eventType: event.eventName,
          payload: event.payload,
        });

        // Fire Postgres NOTIFY so the OutboxListener instantly wakes up
        await tx.execute(sql`SELECT pg_notify('control_plane_outbox_channel', ${outboxId})`);
        index++;
      }

      return row;
    });

    tenant.clearEvents();
    return this.mapToDomain(resultRow, tenant.subscriptions);
  }

  async delete(id: string): Promise<void> {
    // Delete tenant and all dependent records in a transaction
    await this.db.transaction(async (tx) => {
      // Delete tenant_users associations
      await tx.delete(tenantUsers).where(eq(tenantUsers.tenantId, id));

      // Delete api_keys
      await tx.delete(apiKeys).where(eq(apiKeys.tenantId, id));

      // Delete shard_registry
      await tx.delete(shardRegistry).where(eq(shardRegistry.tenantId, id));

      // Delete tenant_subscriptions
      await tx.delete(appSubscriptions).where(eq(appSubscriptions.tenantId, id));

      // Delete outbox events for this tenant
      await tx.delete(controlPlaneOutbox).where(eq(controlPlaneOutbox.tenantId, id));

      // Finally, delete the tenant itself
      await tx.delete(tenants).where(eq(tenants.id, id));
    });
  }

  private async loadSubscriptionSlugs(tenantId: string): Promise<string[]> {
    const subsRows = await this.db
      .select({ slug: apps.slug })
      .from(appSubscriptions)
      .innerJoin(apps, eq(appSubscriptions.appId, apps.id))
      .where(eq(appSubscriptions.tenantId, tenantId));
    return subsRows.map((s) => s.slug);
  }
}
