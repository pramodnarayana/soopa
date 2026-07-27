import { createDbClient, JobStatus, scheduledJobs } from '@soopa/database';
import crypto from 'crypto';
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { PostgresJobRepository } from '../src/adapters/outbound/PostgresJobRepository.js';

describe('PostgresJobRepository', () => {
  const dbConnectionString =
    process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5432/ucp_global';
  let repo: PostgresJobRepository;
  let db: any;

  beforeAll(() => {
    db = createDbClient(dbConnectionString).db;
    repo = new PostgresJobRepository(db, 1000); // 1 second lock lease for tests
  });

  beforeEach(async () => {
    await db.delete(scheduledJobs);
  });

  it('should claim next pending jobs and lock them', async () => {
    const jobId1 = crypto.randomUUID();
    const jobId2 = crypto.randomUUID();

    await db.insert(scheduledJobs).values([
      { id: jobId1, name: 'Job 1', targetQueue: 'q1', payload: {}, status: JobStatus.PENDING },
      { id: jobId2, name: 'Job 2', targetQueue: 'q1', payload: {}, status: JobStatus.PENDING },
    ]);

    const claimed = await repo.claimNextJobs('worker-1', 10);

    expect(claimed.length).toBe(2);
    expect(claimed[0].status).toBe(JobStatus.RUNNING);
    expect(claimed[0].locked_by).toBe('worker-1');
    expect(claimed[1].locked_by).toBe('worker-1');
  });

  it('should mark job as completed', async () => {
    const jobId = crypto.randomUUID();
    await db.insert(scheduledJobs).values({
      id: jobId,
      name: 'Job',
      targetQueue: 'q1',
      payload: {},
      status: JobStatus.RUNNING,
      lockedBy: 'worker',
    });

    await repo.markCompleted(jobId, 'worker');

    const result = await db.query.scheduledJobs.findFirst({
      where: (jobs: any, { eq }: any) => eq(jobs.id, jobId),
    });
    expect(result?.status).toBe(JobStatus.COMPLETED);
    expect(result?.lockedBy).toBeNull();
  });

  it('should mark job as failed', async () => {
    const jobId = crypto.randomUUID();
    await db.insert(scheduledJobs).values({
      id: jobId,
      name: 'Job',
      targetQueue: 'q1',
      payload: {},
      status: JobStatus.RUNNING,
      lockedBy: 'worker',
    });

    await repo.markFailed(jobId, 'worker', 'some error');

    const result = await db.query.scheduledJobs.findFirst({
      where: (jobs: any, { eq }: any) => eq(jobs.id, jobId),
    });
    expect(result?.status).toBe(JobStatus.FAILED);
    expect(result?.errorMessage).toBe('some error');
    expect(result?.lockedBy).toBeNull();
  });

  it('should reschedule job', async () => {
    const jobId = crypto.randomUUID();
    await db.insert(scheduledJobs).values({
      id: jobId,
      name: 'Job',
      targetQueue: 'q1',
      payload: {},
      status: JobStatus.RUNNING,
      lockedBy: 'worker',
    });

    const nextRun = new Date(Date.now() + 10000);
    await repo.reschedule(jobId, 'worker', nextRun);

    const result = await db.query.scheduledJobs.findFirst({
      where: (jobs: any, { eq }: any) => eq(jobs.id, jobId),
    });
    expect(result?.status).toBe(JobStatus.PENDING);
    expect(result?.retryCount).toBe(0);
    // JS dates can lose precision in DB, so check loosely
    expect(result?.nextRunAt?.getTime()).toBeGreaterThanOrEqual(nextRun.getTime() - 1000);
  });

  it('should sweep stuck jobs', async () => {
    const jobId = crypto.randomUUID();
    const oldDate = new Date(Date.now() - 5000); // Older than lockLeaseMs (1000)

    await db.insert(scheduledJobs).values({
      id: jobId,
      name: 'Job',
      targetQueue: 'q1',
      payload: {},
      status: JobStatus.RUNNING,
      lockedBy: 'worker',
      lockedAt: oldDate,
    });

    const swept = await repo.sweepStuckJobs();
    expect(swept).toBe(1);

    const result = await db.query.scheduledJobs.findFirst({
      where: (jobs: any, { eq }: any) => eq(jobs.id, jobId),
    });
    expect(result?.status).toBe(JobStatus.PENDING);
    expect(result?.lockedBy).toBeNull();
  });
});
