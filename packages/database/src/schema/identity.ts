import { pgTable, text, timestamp, varchar, primaryKey } from 'drizzle-orm/pg-core';
import { createId } from '@paralleldrive/cuid2';
import { UserRoles, type UserRoleType } from '../constants.js';

export const tenants = pgTable('tenants', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  name: text('name').notNull(),
  zitadelOrgId: varchar('zitadel_org_id', { length: 255 }), // Nullable if JIT provisioned without explicit org ID
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const users = pgTable('users', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  email: varchar('email', { length: 255 }).notNull().unique(),
  name: text('name').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const tenantUsers = pgTable('tenant_users', {
  tenantId: varchar('tenant_id', { length: 128 }).notNull().references(() => tenants.id),
  userId: varchar('user_id', { length: 128 }).notNull().references(() => users.id),
  role: varchar('role', { length: 50 }).notNull().default(UserRoles.MEMBER).$type<UserRoleType>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => {
  return {
    pk: primaryKey({ columns: [table.tenantId, table.userId] }),
  };
});
