import { describe, it, expect, vi } from 'vitest';
import { Test } from '@nestjs/testing';
import { SchedulerModule } from '../src/SchedulerModule.js';
import { HealthController } from '../src/api/HealthController.js';
import { SchedulerWorker } from '../src/application/SchedulerWorker.js';

// Mock dependencies
vi.mock('@soopa/database', () => ({
  createDbClient: vi.fn().mockReturnValue({ db: {}, pool: { end: vi.fn() } }),
  scheduledJobs: {}
}));

describe('SchedulerModule', () => {
  it('should compile the module and resolve controllers and providers', async () => {
    const moduleRef = await Test.createTestingModule({
      imports: [
        SchedulerModule.register({
          dbConnectionString: 'postgres://dummy',
          engineId: 'test-engine',
          pollIntervalMs: 100,
          batchSize: 5
        })
      ]
    }).compile();

    const healthController = moduleRef.get(HealthController);
    expect(healthController).toBeDefined();

    const worker = moduleRef.get(SchedulerWorker);
    expect(worker).toBeDefined();

    const app = moduleRef.createNestApplication();
    await app.init();
    
    // Test HealthController
    const healthResult = healthController.check();
    expect(healthResult.status).toBe('healthy');
    expect(healthResult.activeJobs).toBe(0);

    // Should call onApplicationBootstrap which calls worker.start()
    // and onApplicationShutdown which calls worker.stop()
    await app.close();
  });
});
