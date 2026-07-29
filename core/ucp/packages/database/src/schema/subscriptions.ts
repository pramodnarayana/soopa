import { createId } from '@paralleldrive/cuid2';
import { sql } from 'drizzle-orm';
import { pgPolicy, primaryKey, text, timestamp, varchar } from 'drizzle-orm/pg-core';
import { tenants } from './identity.js';
import { ucpSchema } from './shared.js';

export const apps = ucpSchema
  .table(
    'apps',
    {
      id: varchar('id', { length: 128 })
        .primaryKey()
        .$defaultFn(() => createId()),
      name: text('name').notNull(),
      slug: varchar('slug', { length: 255 }).notNull().unique(), // e.g., 'edi', 'idp'
      description: text('description'),
      createdAt: timestamp('created_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        rlsPolicy: pgPolicy('apps_isolation', {
          as: 'permissive',
          for: 'all',
          to: 'public',
          using: sql`app.bypass_rls()`,
        }),
        readPolicy: pgPolicy('apps_read', {
          as: 'permissive',
          for: 'select',
          to: 'public',
          using: sql`true`,
        }),
      };
    },
  )
  .enableRLS();

const SubscriptionStatus = {
  ACTIVE: 'active',
  SUSPENDED: 'suspended',
  CANCELLED: 'cancelled',
} as const;
export type SubscriptionStatusType = (typeof SubscriptionStatus)[keyof typeof SubscriptionStatus];

export const tenantSubscriptions = ucpSchema
  .table(
    'tenant_subscriptions',
    {
      tenantId: varchar('tenant_id', { length: 128 })
        .notNull()
        .references(() => tenants.id),
      appId: varchar('app_id', { length: 128 })
        .notNull()
        .references(() => apps.id),
      tier: varchar('tier', { length: 50 }).notNull().default('standard'),
      status: varchar('status', { length: 50 })
        .notNull()
        .default(SubscriptionStatus.ACTIVE)
        .$type<SubscriptionStatusType>(),
      expiresAt: timestamp('expires_at'),
      createdAt: timestamp('created_at').defaultNow().notNull(),
      updatedAt: timestamp('updated_at').defaultNow().notNull(),
    },
    (table) => {
      return {
        pk: primaryKey({ columns: [table.tenantId, table.appId] }),
        rlsPolicy: pgPolicy('tenant_subscriptions_isolation', {
          as: 'permissive',
          for: 'all',
          to: 'public',
          using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`,
        }),
      };
    },
  )
  .enableRLS();
