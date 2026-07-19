import { NotificationChannel } from "@soopa/database";
import * as dotenv from 'dotenv';
dotenv.config();
import fastify from 'fastify';
import notificationRoutes from './api/routes.js';
import { PostgresTemplateRepository } from './adapters/outbound/PostgresTemplateRepository.js';
import { HandlebarsTemplateRenderer } from './adapters/outbound/HandlebarsTemplateRenderer.js';
import { NotificationRendererService } from './domain/services.js';
import { DispatchNotificationUseCase } from './application/DispatchNotificationUseCase.js';

import { StrategyDeliveryDispatcher } from './adapters/outbound/StrategyDeliveryDispatcher.js';
import { EmailDeliveryStrategy } from './adapters/outbound/channels/EmailDeliveryStrategy.js';
import { SlackDeliveryStrategy } from './adapters/outbound/channels/SlackDeliveryStrategy.js';
import { InAppDeliveryStrategy } from './adapters/outbound/channels/InAppDeliveryStrategy.js';
import { IDeliveryService } from './ports/index.js';
import { Channel } from './domain/models.js';

const app = fastify({ logger: true });

// 0. Database Configuration
const dbConnectionString = process.env.DATABASE_URL || 'postgresql://user:password@localhost:5432/platform_shard_1';

// 1. Instantiate Outbound Adapters (Infrastructure)
const templateRepo = new PostgresTemplateRepository(dbConnectionString);
const renderer = new HandlebarsTemplateRenderer();

// 1b. Initialize Strategy Registry for Delivery
const deliveryStrategies = new Map<Channel, IDeliveryService>([
  [NotificationChannel.EMAIL, new EmailDeliveryStrategy()],
  [NotificationChannel.SLACK, new SlackDeliveryStrategy()],
  [NotificationChannel.IN_APP, new InAppDeliveryStrategy()]
]);
const deliveryService = new StrategyDeliveryDispatcher(deliveryStrategies);

// 2. Instantiate Domain Services
const rendererService = new NotificationRendererService(renderer);

// 3. Instantiate Application Use Case (Application Layer)
const dispatchUseCase = new DispatchNotificationUseCase(
  templateRepo,
  deliveryService,
  rendererService
);

// 4. Register Inbound Adapters (REST API)
app.register((instance, _opts, done) => {
  notificationRoutes(instance, dispatchUseCase);
  done();
});

const start = async () => {
  try {
    await app.listen({ port: 3001, host: '0.0.0.0' });
    app.log.info('Notification Engine listening on http://localhost:3001');
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

// Graceful shutdown
const shutdown = async () => {
  app.log.info('Shutting down...');
  await app.close();
  process.exit(0);
};

process.on('SIGINT', () => void shutdown());
process.on('SIGTERM', () => void shutdown());

void start();
