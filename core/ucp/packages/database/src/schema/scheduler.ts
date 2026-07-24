import { createId } from '@paralleldrive/cuid2';
import { index, integer, jsonb, pgTable, text, timestamp, varchar } from 'drizzle-orm/pg-core';

const JobStatus = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
} as const;
type JobStatusType = (typeof JobStatus)[keyof typeof JobStatus];

export const scheduledJobs = pgTable(
  'scheduled_jobs',
  {
    id: varchar('id', { length: 128 })
      .primaryKey()
      .$defaultFn(() => createId()),
    name: varchar('name', { length: 255 }).notNull(),
    payload: jsonb('payload').default({}).notNull(),
    status: varchar('status', { length: 50 })
      .notNull()
      .default(JobStatus.PENDING)
      .$type<JobStatusType>(), // PENDING, RUNNING, COMPLETED, FAILED
    nextRunAt: timestamp('next_run_at'),
    intervalSeconds: integer('interval_seconds'),
    cronExpression: varchar('cron_expression', { length: 100 }),
    targetQueue: varchar('target_queue', { length: 255 }),
    retryCount: integer('retry_count').default(0).notNull(),
    maxRetries: integer('max_retries').default(3).notNull(),
    errorMessage: text('error_message'),
    lockedAt: timestamp('locked_at'),
    lockedBy: varchar('locked_by', { length: 255 }),
    createdAt: timestamp('created_at').defaultNow().notNull(),
    updatedAt: timestamp('updated_at').defaultNow().notNull(),
  },
  (table) => {
    return {
      statusNextRunIdx: index('job_status_next_run_idx').on(table.status, table.nextRunAt),
    };
  },
);
