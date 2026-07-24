import * as dotenv from 'dotenv';

dotenv.config();

import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { NotificationModule } from './NotificationModule.js';

const logger = new Logger('Bootstrap');

async function bootstrap() {
  const app = await NestFactory.create(NotificationModule);

  app.enableShutdownHooks();

  await app.listen(3001, '0.0.0.0');
  logger.log(`Notification Engine listening on ${await app.getUrl()}`);
}

bootstrap().catch((err) => {
  logger.error('Failed to start Notification Engine', err);
  process.exit(1);
});
