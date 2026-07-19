import { PostgresJobRepository } from '../adapters/outbound/PostgresJobRepository.js';
import cronParser from 'cron-parser';

export interface ScheduledJob {
  id: string;
  name: string;
  target_queue: string;
  payload: unknown;
  status: string;
  cron_expression: string | null;
  retry_count: number;
  max_retries: number;
}

export class SchedulerWorker {
  private isRunning = false;
  private timer: NodeJS.Timeout | null = null;
  private activeExecution: Promise<void> | null = null;

  constructor(
    private repository: PostgresJobRepository,
    private workerId: string,
    private pollIntervalMs: number = 5000,
    private maxConcurrentJobs: number = 10
  ) {}

  start() {
    this.isRunning = true;
    console.log(`Starting scheduler worker ${this.workerId} with concurrency ${this.maxConcurrentJobs}`);
    void this.pollLoop();
  }

  async stop() {
    this.isRunning = false;
    if (this.timer) {
      clearTimeout(this.timer);
    }
    if (this.activeExecution) {
      await this.activeExecution;
    }
    console.log(`Stopped scheduler worker ${this.workerId}`);
  }

  private async pollLoop() {
    if (!this.isRunning) return;

    const executionPromise = (async () => {
      try {
        // 1. Sweep stuck jobs (could be optimized to run less frequently)
        const swept = (await this.repository.sweepStuckJobs()) || 0;
        if (swept > 0) {
          console.log(`Swept ${swept} stuck jobs back to JobStatus.PENDING.`);
        }

        // 2. Claim next jobs using SKIP LOCKED
        const jobs = await this.repository.claimNextJobs(this.workerId, this.maxConcurrentJobs);

        if (jobs.length > 0) {
          console.log(`Worker ${this.workerId} claimed ${jobs.length} jobs.`);

          // 3. Execute jobs concurrently without blocking the loop entirely
          const promises = jobs.map((job: unknown) => this.executeJob(job as ScheduledJob));
          await Promise.allSettled(promises);
        }
      } catch (err: unknown) {
        console.error(`Error in scheduler poll loop:`, err);
      }
    })();

    this.activeExecution = executionPromise;
    await executionPromise;

    // 4. Schedule next iteration
    if (this.isRunning) {
      this.timer = setTimeout(() => { void this.pollLoop(); }, this.pollIntervalMs);
    }
  }

  private async executeJob(job: ScheduledJob) {
    try {
      if (!job.target_queue) {
        throw new Error(`No target_queue defined for job ${job.name}`);
      }

      console.log(`Dispatching job ${job.name} (${job.id}) to queue ${job.target_queue}`);
      
      // TODO: Actually dispatch to SQS / Webhook here using a Publisher port
      // For now, we simulate success
      
      // Calculate next run if recurring
      if (job.cron_expression) {
        const interval = cronParser.parseExpression(job.cron_expression);
        const nextRunAt = interval.next().toDate();
        await this.repository.reschedule(job.id, nextRunAt);
        console.log(`Successfully rescheduled job ${job.name} (${job.id}) for ${nextRunAt.toISOString()}`);
      } else {
        await this.repository.markCompleted(job.id);
        console.log(`Successfully completed job ${job.name} (${job.id})`);
      }
    } catch (err: unknown) {
      console.error(`Job ${job.name} (${job.id}) execution failed:`, err);
      
      if (job.retry_count < job.max_retries) {
        const backoffSeconds = 60 * Math.pow(2, job.retry_count);
        const nextRunAt = new Date(Date.now() + backoffSeconds * 1000);
        await this.repository.scheduleRetry(job.id, job.retry_count + 1, nextRunAt);
        console.log(`Scheduled retry for job ${job.name} (${job.id}) at ${nextRunAt.toISOString()}`);
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        await this.repository.markFailed(job.id, msg);
      }
    }
  }
}
