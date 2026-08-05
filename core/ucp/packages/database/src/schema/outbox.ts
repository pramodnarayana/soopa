import { sql } from 'drizzle-orm';
import { index, integer, jsonb, pgPolicy, text, timestamp, varchar } from 'drizzle-orm/pg-core';
import { tenants } from './identity.js';
import { ucpSchema } from './shared.js';

const OutboxStatus = {
  PENDING: 'PENDING',
  PROCESSING: 'PROCESSING',
  PROCESSED: 'PROCESSED',
  FAILED: 'FAILED',
} as const;
export type OutboxStatusType = (typeof OutboxStatus)[keyof typeof OutboxStatus];

export const controlPlaneOutbox = ucpSchema
  .table(
    'outbox',
    {
      // No $defaultFn — id is required. Callers MUST supply generateId('evt').
      id: varchar('id', { length: 128 }).primaryKey(),
      idempotencyKey: varchar('idempotency_key', { length: 255 }).unique().notNull(),
      tenantId: varchar('tenant_id', { length: 128 }).references(() => tenants.id), // Nullable for global events
      eventType: varchar('event_type', { length: 100 }).notNull(),
      payload: jsonb('payload').notNull(),
      status: varchar('status', { length: 50 })
        .notNull()
        .default(OutboxStatus.PENDING)
        .$type<OutboxStatusType>(),
      attempts: integer('attempts').default(0).notNull(),
      publishedAt: timestamp('published_at', { withTimezone: true }),
      ownerToken: varchar('owner_token', { length: 128 }),
      leaseExpiresAt: timestamp('lease_expires_at', { withTimezone: true }),
      errorReason: text('error_reason'),
      createdAt: timestamp('created_at').defaultNow().notNull(),
      updatedAt: timestamp('updated_at').defaultNow().notNull(),
    },
    (table) => [
      index('ix_global_outbox_pending')
        .on(table.status, table.createdAt)
        .where(sql`${table.status} = 'PENDING'`),
      pgPolicy('outbox_isolation', {
        as: 'permissive',
        for: 'all',
        to: 'public',
        using: sql`${table.tenantId} IS NULL OR ${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
        withCheck: sql`${table.tenantId} IS NULL OR ${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
      }),
    ],
  )
  .enableRLS();
