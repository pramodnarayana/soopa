import { Injectable, Inject } from '@nestjs/common';
import { ITenantRepository } from '../../../ports/outbound/tenant.repository';
import { Tenant } from '../../../domain/models/tenant.model';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module';
import {
  tenants,
  tenantSubscriptions,
  tenantUsers,
  apiKeys,
  apps,
  controlPlaneOutbox,
  eq,
} from '@soopa/database';
import type { DbClient } from '@soopa/database';
import { inArray } from 'drizzle-orm';
import { createId } from '@paralleldrive/cuid2';

@Injectable()
export class TenantDrizzleRepository implements ITenantRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private mapToDomain(
    row: typeof tenants.$inferSelect,
    subscriptions: string[] = [],
  ): Tenant {
    return new Tenant(
      row.id,
      row.name,
      row.zitadelOrgId,
      row.status,
      row.createdAt,
      row.updatedAt,
      subscriptions,
    );
  }

  async findById(id: string): Promise<Tenant | null> {
    const [row] = await this.db
      .select()
      .from(tenants)
      .where(eq(tenants.id, id));
    return row ? this.mapToDomain(row) : null;
  }

  async findAll(): Promise<Tenant[]> {
    const rows = await this.db.select().from(tenants);
    return rows.map((row) => this.mapToDomain(row));
  }

  async save(tenant: Tenant): Promise<Tenant> {
    return await this.db.transaction(async (tx) => {
      // 1. Save Tenant
      const [row] = await tx
        .insert(tenants)
        .values({
          id: tenant.id,
          name: tenant.name,
          zitadelOrgId: tenant.zitadelOrgId,
          status: tenant.status,
          createdAt: tenant.createdAt,
          updatedAt: tenant.updatedAt,
        })
        .onConflictDoUpdate({
          target: tenants.id,
          set: {
            name: tenant.name,
            zitadelOrgId: tenant.zitadelOrgId,
            status: tenant.status,
            updatedAt: new Date(),
          },
        })
        .returning();

      // 2. Save Subscriptions
      if (tenant.subscriptions && tenant.subscriptions.length > 0) {
        const dbApps = await tx
          .select()
          .from(apps)
          .where(inArray(apps.slug, tenant.subscriptions));
        if (dbApps.length > 0) {
          const subs = dbApps.map((app) => ({
            tenantId: tenant.id,
            appId: app.id,
            tier: 'standard',
          }));
          await tx
            .insert(tenantSubscriptions)
            .values(subs)
            .onConflictDoNothing();
        }
      }

      // 3. Process Outbox Events (Domain Events)
      for (const event of tenant.domainEvents) {
        await tx.insert(controlPlaneOutbox).values({
          id: createId(),
          idempotencyKey: `${event.eventName}_${tenant.id}_${event.occurredOn.getTime()}`,
          tenantId: tenant.id,
          eventType: event.eventName,
          payload: event.payload,
        });
      }

      tenant.clearEvents();
      return this.mapToDomain(row, tenant.subscriptions);
    });
  }

  async delete(id: string): Promise<void> {
    // Delete tenant and all dependent records in a transaction
    await this.db.transaction(async (tx) => {
      // Delete tenant_users associations
      await tx.delete(tenantUsers).where(eq(tenantUsers.tenantId, id));

      // Delete api_keys
      await tx.delete(apiKeys).where(eq(apiKeys.tenantId, id));

      // Delete tenant_subscriptions
      await tx
        .delete(tenantSubscriptions)
        .where(eq(tenantSubscriptions.tenantId, id));

      // Delete outbox events for this tenant
      await tx
        .delete(controlPlaneOutbox)
        .where(eq(controlPlaneOutbox.tenantId, id));

      // Finally, delete the tenant itself
      await tx.delete(tenants).where(eq(tenants.id, id));
    });
  }
}
