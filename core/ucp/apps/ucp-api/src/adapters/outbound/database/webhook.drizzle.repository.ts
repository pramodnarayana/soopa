import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { and, controlPlaneOutbox, eq, generateId, webhooks } from '@soopa/database';
import { sql } from 'drizzle-orm';
import { Webhook } from '../../../domain/models/webhook.model.js';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import type { IWebhookRepository } from '../../../ports/outbound/webhook.repository.js';

@Injectable()
export class WebhookDrizzleRepository implements IWebhookRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private mapToDomain(row: typeof webhooks.$inferSelect): Webhook {
    return new Webhook(
      row.id,
      row.tenantId,
      row.name,
      row.url,
      row.authHeaderVaultRef,
      row.active,
      row.createdAt,
      row.updatedAt,
    );
  }

  async save(webhook: Webhook, idempotencyKey?: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx
        .insert(webhooks)
        .values({
          id: webhook.id,
          tenantId: webhook.tenantId,
          name: webhook.name,
          url: webhook.url,
          authHeaderVaultRef: webhook.authHeaderVaultRef,
          active: webhook.active,
          createdAt: webhook.createdAt,
          updatedAt: webhook.updatedAt,
        })
        .onConflictDoUpdate({
          target: webhooks.id,
          set: {
            name: webhook.name,
            url: webhook.url,
            authHeaderVaultRef: webhook.authHeaderVaultRef,
            active: webhook.active,
            updatedAt: new Date(),
          },
        });

      const index = 0;
      for (const event of webhook.domainEvents) {
        const outboxId = generateId('evt');
        const finalIdempotencyKey = idempotencyKey
          ? `${idempotencyKey}_${index}`
          : `${event.eventName}_${webhook.id}_${event.occurredOn.getTime()}`;

        await tx.insert(controlPlaneOutbox).values({
          id: outboxId,
          idempotencyKey: finalIdempotencyKey,
          tenantId: webhook.tenantId,
          eventType: event.eventName,
          payload: event.payload,
        });

        // Fire Postgres NOTIFY so the OutboxListener instantly wakes up
        await tx.execute(sql`SELECT pg_notify('control_plane_outbox_channel', ${outboxId})`);
      }
    });
    webhook.clearEvents();
  }

  async findById(tenantId: string, id: string): Promise<Webhook | null> {
    const row = await this.db.query.webhooks.findFirst({
      where: (t, { eq, and }) => and(eq(t.id, id), eq(t.tenantId, tenantId)),
    });
    if (!row) return null;
    return this.mapToDomain(row);
  }

  async findAllByTenant(tenantId: string): Promise<Webhook[]> {
    const rows = await this.db.query.webhooks.findMany({
      where: (t, { eq }) => eq(t.tenantId, tenantId),
      orderBy: (t, { desc }) => [desc(t.createdAt)],
    });
    return rows.map((row) => this.mapToDomain(row));
  }

  async delete(tenantId: string, id: string, idempotencyKey?: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      const result = await tx
        .delete(webhooks)
        .where(and(eq(webhooks.id, id), eq(webhooks.tenantId, tenantId)))
        .returning({ id: webhooks.id });

      if (result.length > 0) {
        const outboxId = generateId('evt');
        const finalIdempotencyKey = idempotencyKey || `webhook.deleted_${id}_${Date.now()}`;
        await tx.insert(controlPlaneOutbox).values({
          id: outboxId,
          idempotencyKey: finalIdempotencyKey,
          tenantId,
          eventType: 'webhook.deleted',
          payload: { resource_id: id },
        });

        // Fire Postgres NOTIFY so the OutboxListener instantly wakes up
        await tx.execute(sql`SELECT pg_notify('control_plane_outbox_channel', ${outboxId})`);
      }
    });
  }
}
