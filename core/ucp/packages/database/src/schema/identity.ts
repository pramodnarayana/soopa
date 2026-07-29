import { createId } from '@paralleldrive/cuid2';
import { sql } from 'drizzle-orm';
import {
  boolean,
  index,
  jsonb,
  pgPolicy,
  primaryKey,
  text,
  timestamp,
  varchar,
} from 'drizzle-orm/pg-core';
import { ucpSchema } from './shared.js';

// User roles are dynamically managed in Zitadel; we store the raw string keys here.

export const tenants = ucpSchema.table('tenants', {
  id: varchar('id', { length: 128 })
    .primaryKey()
    .$defaultFn(() => createId()),
  name: text('name').notNull(),
  zitadelOrgId: varchar('zitadel_org_id', { length: 255 }), // Nullable if JIT provisioned without explicit org ID
  idpTenantId: varchar('idp_tenant_id', { length: 255 }).unique(), // Added to match Python model
  status: varchar('status', { length: 50 })
    .notNull()
    .default('active')
    .$type<'active' | 'inactive'>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const tenantShards = ucpSchema
  .table(
    'tenant_shards',
    {
      tenantId: varchar('tenant_id', { length: 128 })
        .notNull()
        .references(() => tenants.id),
      shardId: varchar('shard_id', { length: 128 }).notNull(),
      shardSchema: varchar('shard_schema', { length: 255 }).notNull().default('public'),
      tier: varchar('tier', { length: 50 }).notNull().default('standard'),
      allowPrivateAs2: boolean('allow_private_as2').notNull().default(false),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        pk: primaryKey({ columns: [table.tenantId, table.shardId] }),
        rlsPolicy: pgPolicy('tenant_shards_isolation', {
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
  id: varchar('id', { length: 128 })
    .primaryKey()
    .$defaultFn(() => createId()),
  idpUserId: varchar('idp_user_id', { length: 255 }).unique(), // Added to match Python model
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
      id: varchar('id', { length: 128 })
        .primaryKey()
        .$defaultFn(() => createId()),
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
