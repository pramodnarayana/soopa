import { Injectable, Inject } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { controlPlaneOutbox } from '@soopa/database';
import {
  IOutboxRepository,
  OutboxEvent,
} from '../../../ports/outbound/outbox.repository';

@Injectable()
export class OutboxDrizzleRepository implements IOutboxRepository {
  constructor(@Inject('DATABASE_CLIENT') private readonly db: any) {}

  async fetchPendingEvents(limit: number): Promise<OutboxEvent[]> {
    const rows = await this.db
      .select()
      .from(controlPlaneOutbox)
      .where(eq(controlPlaneOutbox.status, 'PENDING'))
      .limit(limit);

    return rows.map((row: any) => ({
      id: row.id,
      idempotencyKey: row.idempotencyKey,
      tenantId: row.tenantId,
      eventType: row.eventType,
      payload: row.payload,
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

  async markAsFailed(id: string, error?: string): Promise<void> {
    await this.db
      .update(controlPlaneOutbox)
      .set({ status: 'FAILED', updatedAt: new Date() }) // we don't have an error column yet, so just update status
      .where(eq(controlPlaneOutbox.id, id));
  }
}
