import * as dotenv from 'dotenv';
dotenv.config();
import { NestFactory } from '@nestjs/core';
import { SchedulerModule } from './SchedulerModule.js';
import { Logger } from '@nestjs/common';

const logger = new Logger('Bootstrap');

async function bootstrap() {
  const dbConnectionString = process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_global';
  
  const app = await NestFactory.create(SchedulerModule.register({
    dbConnectionString,
    engineId: 'scheduler-engine',
    pollIntervalMs: 5000,
    batchSize: 10,
  }));
  
  app.enableShutdownHooks();
  
  await app.listen(3001, '0.0.0.0');
  logger.log(`Scheduler Engine listening on ${await app.getUrl()}`);
}

bootstrap().catch(err => {
  logger.error('Failed to start Scheduler Engine', err);
  process.exit(1);
});
