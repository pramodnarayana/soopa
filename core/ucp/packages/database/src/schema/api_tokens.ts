import { createId } from '@paralleldrive/cuid2';
import { sql } from 'drizzle-orm';
import { boolean, index, pgPolicy, timestamp, varchar } from 'drizzle-orm/pg-core';
import { tenants } from './identity.js';
import { ucpSchema } from './shared.js';

export const apiTokens = ucpSchema.table(
  'api_tokens',
  {
    // Using varchar to support CUID or UUID
    id: varchar('id', { length: 128 })
      .primaryKey()
      .$defaultFn(() => createId()),
    tenantId: varchar('tenant_id', { length: 128 })
      .notNull()
      .references(() => tenants.id, { onDelete: 'cascade' }),
    name: varchar('name', { length: 255 }).notNull(),
    clientId: varchar('client_id', { length: 64 }).notNull().unique(),
    secretHash: varchar('secret_hash', { length: 64 }).notNull(),
    lastUsedAt: timestamp('last_used_at', { withTimezone: true }),
    expiresAt: timestamp('expires_at', { withTimezone: true }),
    active: boolean('active').default(true).notNull(),
    createdAt: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => {
    return {
      tenantIdx: index('api_tokens_tenant_idx').on(table.tenantId),
      rlsPolicy: pgPolicy('api_tokens_isolation', {
        as: 'permissive',
        for: 'all',
        to: 'public',
        using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
      }),
    };
  },
);
