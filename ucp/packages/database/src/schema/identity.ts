import { pgTable, text, timestamp, varchar, primaryKey, jsonb, index } from 'drizzle-orm/pg-core';
import { createId } from '@paralleldrive/cuid2';

const UserRoles = { ADMIN: 'admin', MEMBER: 'member' } as const;
export type UserRoleType = typeof UserRoles[keyof typeof UserRoles];

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
  role: varchar('role', { length: 50 }).notNull().default(UserRoles.MEMBER).$type<UserRoleType>(),
  metadata: jsonb('metadata'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => {
  return {
    pk: primaryKey({ columns: [table.tenantId, table.userId] }),
    userIdIdx: index('tenant_users_user_id_idx').on(table.userId),
  };
});

export const apiKeys = pgTable('api_keys', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  tenantId: varchar('tenant_id', { length: 128 }).notNull().references(() => tenants.id),
  keyHash: text('key_hash').notNull().unique(),
  name: text('name').notNull(),
  scopes: text('scopes').array().notNull().default([]),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});
