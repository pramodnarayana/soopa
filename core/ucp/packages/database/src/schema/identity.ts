import { pgTable, text, timestamp, varchar, primaryKey, jsonb, index, pgPolicy } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';
import { createId } from '@paralleldrive/cuid2';

// User roles are dynamically managed in Zitadel; we store the raw string keys here.

export const tenants = pgTable('tenants', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  name: text('name').notNull(),
  zitadelOrgId: varchar('zitadel_org_id', { length: 255 }), // Nullable if JIT provisioned without explicit org ID
  status: varchar('status', { length: 50 }).notNull().default('active').$type<'active' | 'inactive'>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const users = pgTable('users', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  email: varchar('email', { length: 255 }).notNull().unique(),
  name: text('name').notNull(),
  status: varchar('status', { length: 50 }).notNull().default('active').$type<'active' | 'inactive'>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const tenantUsers = pgTable('tenant_users', {
  tenantId: varchar('tenant_id', { length: 128 }).notNull().references(() => tenants.id),
  userId: varchar('user_id', { length: 128 }).notNull().references(() => users.id),
  role: varchar('role', { length: 50 }).notNull(),
  metadata: jsonb('metadata'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => {
  return {
    pk: primaryKey({ columns: [table.tenantId, table.userId] }),
    userIdIdx: index('tenant_users_user_id_idx').on(table.userId),
    rlsPolicy: pgPolicy('tenant_users_isolation', {
      as: 'permissive',
      for: 'all',
      to: 'public',
      using: sql`${table.tenantId} = current_setting('app.current_tenant_id', true) OR current_setting('app.bypass_rls', true) = 'on'`
    })
  };
});

export const apiKeys = pgTable('api_keys', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  tenantId: varchar('tenant_id', { length: 128 }).notNull().references(() => tenants.id),
  keyHash: text('key_hash').notNull().unique(),
  name: text('name').notNull(),
  scopes: text('scopes').array().notNull().default([]),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => [
  pgPolicy('api_keys_isolation', {
    as: 'permissive',
    for: 'all',
    to: 'public',
    using: sql`${table.tenantId} = current_setting('app.current_tenant_id', true) OR current_setting('app.bypass_rls', true) = 'on'`
  })
]);
