import { NestFactory } from '@nestjs/core';
import { FastifyAdapter, NestFastifyApplication } from '@nestjs/platform-fastify';
import { Logger } from 'nestjs-pino';
import { GlobalExceptionFilter } from './adapters/inbound/http/filters/global-exception.filter.js';
import { AppModule } from './app.module.js';

async function bootstrap() {
  const app = await NestFactory.create<NestFastifyApplication>(AppModule, new FastifyAdapter(), {
    bufferLogs: true,
    rawBody: true,
  });

  app.useLogger(app.get(Logger));
  app.useGlobalFilters(new GlobalExceptionFilter());

  app.enableCors({
    origin: process.env.FRONTEND_URL || 'http://localhost:5173',
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE,OPTIONS',
    credentials: true,
  });

  app.enableShutdownHooks();

  const port = process.env.PORT ?? 3000;
  await app.listen(port, '0.0.0.0');

  const logger = app.get(Logger);
  logger.log(`UCP Backend API (Fastify) is running on: http://localhost:${port}`);
  logger.log(
    `Platform Dashboard (Frontend) is running on: ${process.env.FRONTEND_URL || 'http://localhost:5173'}`,
  );
}
void bootstrap();
