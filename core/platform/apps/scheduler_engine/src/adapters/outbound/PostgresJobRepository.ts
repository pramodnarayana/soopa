import { and, createDbClient, eq, JobStatus, scheduledJobs, sql } from '@soopa/database';

export class PostgresJobRepository {
  constructor(
    private db: ReturnType<typeof createDbClient>['db'],
    private lockLeaseMs: number = 300000,
  ) {}

  async claimNextJobs(workerId: string, limit: number) {
    const threshold = new Date(Date.now() - this.lockLeaseMs);
    const now = new Date();

    // In Drizzle, doing SKIP LOCKED requires raw SQL for now, or a very specific Query Builder sequence.
    // For simplicity, we use raw SQL to ensure exact SKIP LOCKED behavior identical to Python.
    const query = sql`
      UPDATE ucp.scheduled_jobs
      SET status = ${JobStatus.RUNNING}, locked_at = ${now.toISOString()}, locked_by = ${workerId}
      WHERE id IN (
        SELECT id FROM ucp.scheduled_jobs
        WHERE (status = ${JobStatus.PENDING} OR (status = ${JobStatus.RUNNING} AND locked_at < ${threshold.toISOString()}))
          AND (next_run_at IS NULL OR next_run_at <= ${now.toISOString()})
        ORDER BY next_run_at ASC NULLS FIRST, created_at ASC
        LIMIT ${limit}
        FOR UPDATE SKIP LOCKED
      )
      RETURNING *;
    `;

    const result = await this.db.execute(query);
    return result.rows;
  }

  async markCompleted(jobId: string, workerId: string) {
    await this.db
      .update(scheduledJobs)
      .set({ status: JobStatus.COMPLETED, lockedAt: null, lockedBy: null })
      .where(
        and(
          eq(scheduledJobs.id, jobId),
          eq(scheduledJobs.status, JobStatus.RUNNING),
          eq(scheduledJobs.lockedBy, workerId),
        ),
      );
  }

  async markFailed(jobId: string, workerId: string, error: string) {
    await this.db
      .update(scheduledJobs)
      .set({ status: JobStatus.FAILED, lockedAt: null, lockedBy: null, errorMessage: error })
      .where(
        and(
          eq(scheduledJobs.id, jobId),
          eq(scheduledJobs.status, JobStatus.RUNNING),
          eq(scheduledJobs.lockedBy, workerId),
        ),
      );
  }

  async reschedule(jobId: string, workerId: string, nextRunAt: Date) {
    await this.db
      .update(scheduledJobs)
      .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null, retryCount: 0, nextRunAt })
      .where(
        and(
          eq(scheduledJobs.id, jobId),
          eq(scheduledJobs.status, JobStatus.RUNNING),
          eq(scheduledJobs.lockedBy, workerId),
        ),
      );
  }

  async scheduleRetry(jobId: string, workerId: string, retryCount: number, nextRunAt: Date) {
    await this.db
      .update(scheduledJobs)
      .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null, retryCount, nextRunAt })
      .where(
        and(
          eq(scheduledJobs.id, jobId),
          eq(scheduledJobs.status, JobStatus.RUNNING),
          eq(scheduledJobs.lockedBy, workerId),
        ),
      );
  }

  async sweepStuckJobs() {
    const threshold = new Date(Date.now() - this.lockLeaseMs);

    try {
      const result = await this.db
        .update(scheduledJobs)
        .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null })
        .where(
          and(
            eq(scheduledJobs.status, JobStatus.RUNNING),
            sql`${scheduledJobs.lockedAt} <= ${threshold.toISOString()}::timestamp`,
          ),
        );
      return result.rowCount;
    } catch (err: unknown) {
      let errorMsg: string;
      if (err instanceof Error) {
        errorMsg = err.message;
      } else if (typeof err === 'object' && err !== null) {
        try {
          errorMsg = JSON.stringify(err);
        } catch {
          errorMsg = 'Unknown object error';
        }
      } else {
        errorMsg = String(err);
      }
      const error = err instanceof Error ? err : new Error(errorMsg);
      console.error('Deep Drizzle Error Details:', error, 'Cause:', error.cause);
      throw error;
    }
  }
}
