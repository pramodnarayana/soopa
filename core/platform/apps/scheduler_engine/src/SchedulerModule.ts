import {
  Global,
  Module,
  OnApplicationBootstrap,
  OnApplicationShutdown,
  Provider,
} from '@nestjs/common';
import { createDbClient } from '@soopa/database';
import pg from 'pg';
import { PostgresJobRepository } from './adapters/outbound/PostgresJobRepository.js';
import { HealthController } from './api/HealthController.js';
import { SchedulerWorker } from './application/SchedulerWorker.js';

export interface SchedulerModuleOptions {
  dbConnectionString: string;
  engineId: string;
  pollIntervalMs: number;
  batchSize: number;
}

@Global()
@Module({})
export class SchedulerModule implements OnApplicationBootstrap, OnApplicationShutdown {
  constructor(
    private readonly worker: SchedulerWorker,
    private readonly pool: pg.Pool,
  ) {}

  async onApplicationBootstrap() {
    void this.worker.start();
  }

  async onApplicationShutdown() {
    await this.worker.stop();
    await this.pool.end();
  }

  static register(options: SchedulerModuleOptions) {
    const dbClient = createDbClient(options.dbConnectionString);

    const dbProvider: Provider = {
      provide: 'DATABASE_CONNECTION',
      useValue: dbClient.db,
    };

    const poolProvider: Provider = {
      provide: pg.Pool,
      useValue: dbClient.pool,
    };

    const repoProvider: Provider = {
      provide: PostgresJobRepository,
      useFactory: (db: ReturnType<typeof createDbClient>['db']) => {
        return new PostgresJobRepository(db);
      },
      inject: ['DATABASE_CONNECTION'],
    };

    const workerProvider: Provider = {
      provide: SchedulerWorker,
      useFactory: (repo: PostgresJobRepository) => {
        return new SchedulerWorker(
          repo,
          options.engineId,
          options.pollIntervalMs,
          options.batchSize,
        );
      },
      inject: [PostgresJobRepository],
    };

    return {
      module: SchedulerModule,
      controllers: [HealthController],
      providers: [dbProvider, poolProvider, repoProvider, workerProvider],
      exports: [SchedulerWorker],
    };
  }
}
