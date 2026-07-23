import { pgTable, serial, varchar, text, boolean, uniqueIndex, pgPolicy } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';

export type NotificationChannelType = 'EMAIL' | 'SLACK' | 'IN_APP';

export const notificationTemplates = pgTable('notification_templates', {
  id: serial('id').primaryKey(),
  tenantId: varchar('tenant_id', { length: 255 }).notNull(),
  eventType: varchar('event_type', { length: 255 }).notNull(),
  channel: varchar('channel', { length: 50 }).notNull().$type<NotificationChannelType>(),
  subjectTemplate: text('subject_template').notNull(),
  bodyTemplate: text('body_template').notNull(),
  isActive: boolean('is_active').default(true).notNull(),
}, (table) => {
  return {
    notificationTemplateIdx: uniqueIndex('notification_template_idx').on(table.tenantId, table.eventType, table.channel),
    rlsPolicy: pgPolicy('notification_templates_isolation', {
      as: 'permissive',
      for: 'all',
      to: 'public',
      using: sql`${table.tenantId} = app.current_tenant_id() OR app.bypass_rls()`
    })
  };
});
