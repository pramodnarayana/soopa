import { JobStatus } from "@soopa/database";
import { scheduledJobs, createDbClient, eq, sql, and, lte } from '@soopa/database';

export class PostgresJobRepository {
  constructor(private db: ReturnType<typeof createDbClient>['db'], private lockLeaseMs: number = 300000) {}

  async claimNextJobs(workerId: string, limit: number) {
    const threshold = new Date(Date.now() - this.lockLeaseMs);
    const now = new Date();
    
    // In Drizzle, doing SKIP LOCKED requires raw SQL for now, or a very specific Query Builder sequence.
    // For simplicity, we use raw SQL to ensure exact SKIP LOCKED behavior identical to Python.
    const query = sql`
      UPDATE scheduled_jobs
      SET status = ${JobStatus.RUNNING}, locked_at = ${now.toISOString()}, locked_by = ${workerId}
      WHERE id IN (
        SELECT id FROM scheduled_jobs
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

  async markCompleted(jobId: string) {
    await this.db.update(scheduledJobs)
      .set({ status: JobStatus.COMPLETED, lockedAt: null, lockedBy: null })
      .where(eq(scheduledJobs.id as never, jobId));
  }

  async markFailed(jobId: string, error: string) {
    await this.db.update(scheduledJobs)
      .set({ status: JobStatus.FAILED, lockedAt: null, lockedBy: null, errorMessage: error })
      .where(eq(scheduledJobs.id as never, jobId));
  }

  async reschedule(jobId: string, nextRunAt: Date) {
    await this.db.update(scheduledJobs)
      .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null, retryCount: 0, nextRunAt })
      .where(eq(scheduledJobs.id as never, jobId));
  }

  async scheduleRetry(jobId: string, retryCount: number, nextRunAt: Date) {
    await this.db.update(scheduledJobs)
      .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null, retryCount, nextRunAt })
      .where(eq(scheduledJobs.id as never, jobId));
  }

  async sweepStuckJobs() {
    const threshold = new Date(Date.now() - this.lockLeaseMs);
    
    const result = await this.db.update(scheduledJobs)
      .set({ status: JobStatus.PENDING, lockedAt: null, lockedBy: null })
      .where(
        and(
          eq(scheduledJobs.status as never, JobStatus.RUNNING),
          lte(scheduledJobs.lockedAt as never, threshold)
        )
      );
    return result.rowCount;
  }
}
