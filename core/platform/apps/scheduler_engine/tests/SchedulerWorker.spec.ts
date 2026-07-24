import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SchedulerWorker } from '../src/application/SchedulerWorker.js';

describe('SchedulerWorker', () => {
  let worker: SchedulerWorker;
  let mockRepo: any;

  beforeEach(() => {
    vi.useFakeTimers();
    mockRepo = {
      sweepStuckJobs: vi.fn().mockResolvedValue(0),
      claimNextJobs: vi.fn().mockResolvedValue([]),
      markCompleted: vi.fn().mockResolvedValue(undefined),
      markFailed: vi.fn().mockResolvedValue(undefined),
      reschedule: vi.fn().mockResolvedValue(undefined),
      scheduleRetry: vi.fn().mockResolvedValue(undefined),
    };
    worker = new SchedulerWorker(mockRepo, 'test-worker', 1000, 10);
  });

  afterEach(async () => {
    await worker.stop();
    vi.useRealTimers();
  });

  it('should start and poll', async () => {
    worker.start();

    // Fast forward to trigger the next poll
    await vi.runOnlyPendingTimersAsync();

    expect(mockRepo.sweepStuckJobs).toHaveBeenCalled();
    expect(mockRepo.claimNextJobs).toHaveBeenCalledWith('test-worker', 10);
  });

  it('should process job and mark completed', async () => {
    mockRepo.claimNextJobs.mockResolvedValueOnce([
      { id: 'j1', name: 'Job 1', target_queue: 'q1', payload: {} },
    ]);

    worker.start();
    await vi.runOnlyPendingTimersAsync();

    expect(mockRepo.markCompleted).toHaveBeenCalledWith('j1', 'test-worker');
  });

  it('should reschedule recurring job', async () => {
    mockRepo.claimNextJobs.mockResolvedValueOnce([
      { id: 'j2', name: 'Job 2', target_queue: 'q1', payload: {}, cron_expression: '* * * * *' },
    ]);

    worker.start();
    await vi.runOnlyPendingTimersAsync();

    expect(mockRepo.reschedule).toHaveBeenCalledWith('j2', 'test-worker', expect.any(Date));
  });

  it('should fail if no target queue', async () => {
    mockRepo.claimNextJobs.mockResolvedValueOnce([
      { id: 'j3', name: 'Job 3', target_queue: null, payload: {}, retry_count: 0, max_retries: 3 },
    ]);

    worker.start();
    await vi.runOnlyPendingTimersAsync();

    expect(mockRepo.scheduleRetry).toHaveBeenCalledWith('j3', 'test-worker', 1, expect.any(Date));
  });

  it('should mark failed if max retries exceeded', async () => {
    mockRepo.claimNextJobs.mockResolvedValueOnce([
      { id: 'j4', name: 'Job 4', target_queue: null, payload: {}, retry_count: 3, max_retries: 3 },
    ]);

    worker.start();
    await vi.runOnlyPendingTimersAsync();

    expect(mockRepo.markFailed).toHaveBeenCalledWith('j4', 'test-worker', expect.any(String));
  });
});
