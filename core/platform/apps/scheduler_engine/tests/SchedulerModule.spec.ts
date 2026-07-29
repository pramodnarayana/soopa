import { Test } from '@nestjs/testing';
import { describe, expect, it } from 'vitest';
import { HealthController } from '../src/api/HealthController.js';
import { SchedulerWorker } from '../src/application/SchedulerWorker.js';
import { SchedulerModule } from '../src/SchedulerModule.js';

describe('SchedulerModule', () => {
  const dbConnectionString =
    process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5432/ucp_global';

  it('should compile the module and resolve controllers and providers', async () => {
    const moduleRef = await Test.createTestingModule({
      imports: [
        SchedulerModule.register({
          dbConnectionString,
          engineId: 'test-engine',
          pollIntervalMs: 100,
          batchSize: 5,
        }),
      ],
    }).compile();

    const healthController = moduleRef.get(HealthController);
    expect(healthController).toBeDefined();

    const worker = moduleRef.get(SchedulerWorker);
    expect(worker).toBeDefined();

    const app = moduleRef.createNestApplication();
    await app.init();

    // Give the worker loop a chance to run at least once against the real database
    // This will trigger sweepStuckJobs and test the actual DB connection/schema
    await new Promise((resolve) => setTimeout(resolve, 300));

    // Test HealthController
    const healthResult = healthController.check();
    expect(healthResult.status).toBe('healthy');
    expect(healthResult.activeJobs).toBe(0);

    // Should call onApplicationBootstrap which calls worker.start()
    // and onApplicationShutdown which calls worker.stop()
    await app.close();
  });
});
