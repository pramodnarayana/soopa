import { sql } from 'drizzle-orm';
import { index, jsonb, pgPolicy, primaryKey, text, timestamp, varchar } from 'drizzle-orm/pg-core';
import { ucpSchema } from './shared.js';

// User roles are dynamically managed in Zitadel; we store the raw string keys here.

export const tenants = ucpSchema.table('tenants', {
  // No $defaultFn — id is required at the TypeScript level. Callers MUST supply
  // a prefixed ID via generateId('ten') from @soopa/database.
  id: varchar('id', { length: 128 }).primaryKey(),
  name: text('name').notNull(),
  idpTenantId: varchar('idp_tenant_id', { length: 255 }).unique(),
  status: varchar('status', { length: 50 })
    .notNull()
    .default('active')
    .$type<'active' | 'inactive'>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const shardRegistry = ucpSchema
  .table(
    'shard_registry',
    {
      tenantId: varchar('tenant_id', { length: 128 })
        .notNull()
        .references(() => tenants.id),
      appId: varchar('app_id', { length: 128 }).notNull(),
      shardId: varchar('shard_id', { length: 128 }).notNull(),
      status: varchar('status', { length: 50 })
        .notNull()
        .default('active')
        .$type<'active' | 'inactive'>(),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        pk: primaryKey({ columns: [table.tenantId, table.appId] }),
        rlsPolicy: pgPolicy('shard_registry_isolation', {
          as: 'permissive',
          for: 'all',
          to: 'public',
          using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
        }),
      };
    },
  )
  .enableRLS();

export const users = ucpSchema.table('users', {
  // No $defaultFn — id is required. Callers MUST supply generateId('usr').
  id: varchar('id', { length: 128 }).primaryKey(),
  idpUserId: varchar('idp_user_id', { length: 255 }).unique(),
  email: varchar('email', { length: 255 }).notNull().unique(),
  name: text('name').notNull(),
  status: varchar('status', { length: 50 })
    .notNull()
    .default('active')
    .$type<'active' | 'inactive'>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const tenantUsers = ucpSchema
  .table(
    'tenant_users',
    {
      tenantId: varchar('tenant_id', { length: 128 })
        .notNull()
        .references(() => tenants.id),
      userId: varchar('user_id', { length: 128 })
        .notNull()
        .references(() => users.id),
      role: varchar('role', { length: 50 }).notNull(),
      metadata: jsonb('metadata'),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        pk: primaryKey({ columns: [table.tenantId, table.userId] }),
        userIdIdx: index('tenant_users_user_id_idx').on(table.userId),
        rlsPolicy: pgPolicy('tenant_users_isolation', {
          as: 'permissive',
          for: 'all',
          to: 'public',
          using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
        }),
      };
    },
  )
  .enableRLS();

export const apiKeys = ucpSchema
  .table(
    'api_keys',
    {
      // No $defaultFn — id is required. Callers MUST supply generateId('key').
      id: varchar('id', { length: 128 }).primaryKey(),
      tenantId: varchar('tenant_id', { length: 128 })
        .notNull()
        .references(() => tenants.id),
      keyHash: text('key_hash').notNull().unique(),
      name: text('name').notNull(),
      scopes: text('scopes').array().notNull().default([]),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        tenantIdx: index('api_keys_tenant_idx').on(table.tenantId),
        rlsPolicy: pgPolicy('api_keys_isolation', {
          as: 'permissive',
          for: 'all',
          to: 'public',
          using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
        }),
      };
    },
  )
  .enableRLS();
