import { Inject, Injectable, Logger } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { sql } from 'drizzle-orm';
import { type AnyPgTable, integer, jsonb, pgSchema, timestamp, varchar } from 'drizzle-orm/pg-core';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import { ITargetControlPlaneOutboxRepository } from '../../../ports/outbound/target-control-plane-outbox.repository.js';

export class InvalidOutboxTargetException extends Error {
  constructor(appSlug: string) {
    super(`Invalid app slug format: ${appSlug}`);
    this.name = 'InvalidOutboxTargetException';
  }
}

@Injectable()
export class TargetControlPlaneOutboxDrizzleRepository
  implements ITargetControlPlaneOutboxRepository
{
  private readonly logger = new Logger(TargetControlPlaneOutboxDrizzleRepository.name);

  // Cache the dynamically generated schema objects to prevent memory leaks
  private readonly schemaCache = new Map<string, AnyPgTable>();

  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private getTargetOutboxTable(appSlug: string) {
    if (this.schemaCache.has(appSlug)) {
      return this.schemaCache.get(appSlug)!;
    }
    const targetSchema = pgSchema(appSlug);
    const targetOutbox = targetSchema.table('outbox', {
      id: varchar('id').primaryKey(),
      idempotencyKey: varchar('idempotency_key'),
      tenantId: varchar('tenant_id'),
      eventType: varchar('event_type'),
      payload: jsonb('payload'),
      status: varchar('status'),
      attempts: integer('attempts'),
      createdAt: timestamp('created_at'),
    });
    this.schemaCache.set(appSlug, targetOutbox);
    return targetOutbox;
  }

  // Strictly type the payload as a generic Record to prevent dangerous spread operations
  async publishToApp<T extends Record<string, unknown>>(
    appSlug: string,
    event: {
      id: string;
      tenantId: string | null;
      eventType: string;
      payload: T;
    },
  ): Promise<void> {
    try {
      if (!/^[a-z0-9_]+$/.test(appSlug)) {
        throw new InvalidOutboxTargetException(appSlug);
      }

      const targetOutbox = this.getTargetOutboxTable(appSlug);

      await this.db.transaction(async (tx) => {
        await tx
          .insert(targetOutbox)
          .values({
            id: event.id,
            idempotencyKey: event.id, // using event id as idempotency key for this fan-out
            tenantId: event.tenantId,
            eventType: event.eventType,
            payload: event.payload,
            status: 'PENDING',
            attempts: 0,
            createdAt: new Date(),
          })
          .onConflictDoNothing();

        await tx.execute(sql`SELECT pg_notify(${appSlug + '_outbox_channel'}, ${event.id})`);
      });

      this.logger.debug(`Published event ${event.id} to ${appSlug}.outbox`);
    } catch (error) {
      this.logger.error(`Failed to publish event ${event.id} to ${appSlug}.outbox`, error);
      throw error;
    }
  }
}
