import { createId } from '@paralleldrive/cuid2';
import { sql } from 'drizzle-orm';
import { boolean, index, pgPolicy, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { tenants } from './identity.js';

export const webhooks = pgTable(
  'webhooks',
  {
    id: varchar('id', { length: 128 })
      .primaryKey()
      .$defaultFn(() => createId()),
    tenantId: varchar('tenant_id', { length: 128 })
      .notNull()
      .references(() => tenants.id, { onDelete: 'cascade' }),
    name: varchar('name', { length: 255 }).notNull(),
    url: varchar('url', { length: 1024 }).notNull(),
    authHeaderVaultRef: varchar('auth_header_vault_ref', { length: 255 }),
    active: boolean('active').default(true).notNull(),
    createdAt: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => {
    return {
      tenantIdx: index('webhooks_tenant_idx').on(table.tenantId),
      rlsPolicy: pgPolicy('webhooks_isolation', {
        as: 'permissive',
        for: 'all',
        to: 'public',
        using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
      }),
    };
  },
);
