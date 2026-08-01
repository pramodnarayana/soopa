import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import {
  and,
  controlPlaneOutbox,
  eq,
  generateId,
  webhooks,
} from '@soopa/database';
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

  async save(webhook: Webhook): Promise<void> {
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

      for (const event of webhook.domainEvents) {
        await tx.insert(controlPlaneOutbox).values({
          id: generateId('evt'),
          idempotencyKey: `${event.eventName}_${webhook.id}_${event.occurredOn.getTime()}`,
          tenantId: webhook.tenantId,
          eventType: event.eventName,
          payload: event.payload,
        });
      }
      webhook.clearEvents();
    });
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

  async delete(tenantId: string, id: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx
        .delete(webhooks)
        .where(and(eq(webhooks.id, id), eq(webhooks.tenantId, tenantId)));
      await tx.insert(controlPlaneOutbox).values({
        id: generateId('evt'),
        idempotencyKey: `webhook.deleted_${id}_${Date.now()}`,
        tenantId,
        eventType: 'webhook.deleted',
        payload: { resource_id: id },
      });
    });
  }
}
