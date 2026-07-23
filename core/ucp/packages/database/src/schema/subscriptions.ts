import { pgTable, text, timestamp, varchar, primaryKey, pgPolicy } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';
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
    rlsPolicy: pgPolicy('tenant_subscriptions_isolation', {
      as: 'permissive',
      for: 'all',
      to: 'public',
      using: sql`${table.tenantId} = current_setting('app.current_tenant_id', true) OR current_setting('app.bypass_rls', true) = 'on'`
    })
  };
});
