import { pgTable, text, timestamp, varchar, primaryKey } from 'drizzle-orm/pg-core';
import { createId } from '@paralleldrive/cuid2';
import { tenants } from './identity';

export const apps = pgTable('apps', {
  id: varchar('id', { length: 128 }).primaryKey().$defaultFn(() => createId()),
  name: text('name').notNull(),
  slug: varchar('slug', { length: 255 }).notNull().unique(), // e.g., 'edi', 'idp'
  description: text('description'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

const SubscriptionStatus = { ACTIVE: 'active', SUSPENDED: 'suspended', CANCELLED: 'cancelled' } as const;
export type SubscriptionStatusType = typeof SubscriptionStatus[keyof typeof SubscriptionStatus];

export const tenantSubscriptions = pgTable('tenant_subscriptions', {
  tenantId: varchar('tenant_id', { length: 128 }).notNull().references(() => tenants.id),
  appId: varchar('app_id', { length: 128 }).notNull().references(() => apps.id),
  tier: varchar('tier', { length: 50 }).notNull().default('standard'),
  status: varchar('status', { length: 50 }).notNull().default(SubscriptionStatus.ACTIVE).$type<SubscriptionStatusType>(),
  expiresAt: timestamp('expires_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => {
  return {
    pk: primaryKey({ columns: [table.tenantId, table.appId] }),
  };
});
