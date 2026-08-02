import { sql } from 'drizzle-orm';
import { index, jsonb, pgPolicy, timestamp, varchar } from 'drizzle-orm/pg-core';
import { ucpSchema } from './shared.js';

export const databaseShards = ucpSchema.table('database_shards', {
  // No $defaultFn — id is required. Callers MUST supply generateId('shard').
  id: varchar('id', { length: 128 }).primaryKey(),
  name: varchar('name', { length: 255 }).notNull().unique(),
  dsn: varchar('dsn', { length: 1024 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const platformSettings = ucpSchema.table('platform_settings', {
  key: varchar('key').primaryKey(),
  value: jsonb('value'),
  createdAt: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
});

export const systemAuditLog = ucpSchema
  .table(
    'system_audit_log',
    {
      // No $defaultFn — id is required. Callers MUST supply generateId('aud').
      id: varchar('id', { length: 128 }).primaryKey(),
      traceId: varchar('trace_id', { length: 128 }).notNull(),
      tenantId: varchar('tenant_id', { length: 128 }).notNull(),
      event: varchar('event', { length: 100 }).notNull(),
      status: varchar('status', { length: 50 }).notNull(),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => [
      index('ix_system_audit_log_tenant_time').on(table.tenantId, table.createdAt),
      index('ix_ucp_system_audit_log_trace_id').on(table.traceId),
      pgPolicy('system_audit_log_isolation', {
        as: 'permissive',
        for: 'all',
        to: 'public',
        using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
      }),
    ],
  )
  .enableRLS();
