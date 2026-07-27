import * as dotenv from 'dotenv';
import { fileURLToPath } from 'node:url';
import * as path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '../../../../.env') });

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
