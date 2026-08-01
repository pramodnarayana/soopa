import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { controlPlaneOutbox } from '@soopa/database';
import { eq, inArray } from 'drizzle-orm';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import {
  IOutboxRepository,
  OutboxEvent,
} from '../../../ports/outbound/outbox.repository.js';

@Injectable()
export class OutboxDrizzleRepository implements IOutboxRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  async fetchPendingEvents(limit: number): Promise<OutboxEvent[]> {
    const rows = await this.db.transaction(async (tx) => {
      // 1. Find pending IDs with a lock
      const pendingIds = await tx
        .select({ id: controlPlaneOutbox.id })
        .from(controlPlaneOutbox)
        .where(eq(controlPlaneOutbox.status, 'PENDING'))
        .limit(limit)
        .for('update', { skipLocked: true });

      if (pendingIds.length === 0) {
        return [];
      }

      // 2. Atomically update them to PROCESSING and return them
      const ids = pendingIds.map((p) => p.id);
      return tx
        .update(controlPlaneOutbox)
        .set({ status: 'PROCESSING', updatedAt: new Date() })
        .where(inArray(controlPlaneOutbox.id, ids))
        .returning();
    });

    return rows.map((row) => ({
      id: row.id,
      idempotencyKey: row.idempotencyKey,
      tenantId: row.tenantId ?? '',
      eventType: row.eventType,
      payload: row.payload as Record<string, unknown>,
      status: row.status,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    }));
  }

  async markAsProcessed(id: string): Promise<void> {
    await this.db
      .update(controlPlaneOutbox)
      .set({ status: 'PROCESSED', updatedAt: new Date() })
      .where(eq(controlPlaneOutbox.id, id));
  }

  async markAsFailed(id: string, errorReason?: string): Promise<void> {
    await this.db
      .update(controlPlaneOutbox)
      .set({ status: 'FAILED', updatedAt: new Date(), errorReason })
      .where(eq(controlPlaneOutbox.id, id));
  }
}
