import { Module, Provider } from '@nestjs/common';
import { NotificationChannel } from '@soopa/database';
import { EmailDeliveryStrategy } from './adapters/outbound/channels/EmailDeliveryStrategy.js';
import { InAppDeliveryStrategy } from './adapters/outbound/channels/InAppDeliveryStrategy.js';
import { SlackDeliveryStrategy } from './adapters/outbound/channels/SlackDeliveryStrategy.js';
import { HandlebarsTemplateRenderer } from './adapters/outbound/HandlebarsTemplateRenderer.js';
import { PostgresTemplateRepository } from './adapters/outbound/PostgresTemplateRepository.js';
import { StrategyDeliveryDispatcher } from './adapters/outbound/StrategyDeliveryDispatcher.js';
import { NotificationController } from './api/NotificationController.js';
import { DispatchNotificationUseCase } from './application/DispatchNotificationUseCase.js';
import { Channel } from './domain/models.js';
import { NotificationRendererService } from './domain/services.js';
import { IDeliveryService, ITemplateRepository } from './ports/index.js';

const dbConnectionString =
  process.env.DATABASE_URL || 'postgresql://user:password@localhost:5432/platform_shard_1';

const repoProvider: Provider = {
  provide: 'ITemplateRepository',
  useFactory: () => {
    return new PostgresTemplateRepository(dbConnectionString);
  },
};

const rendererProvider: Provider = {
  provide: HandlebarsTemplateRenderer,
  useClass: HandlebarsTemplateRenderer,
};

const deliveryServiceProvider: Provider = {
  provide: 'IDeliveryService',
  useFactory: () => {
    const deliveryStrategies = new Map<Channel, IDeliveryService>([
      [NotificationChannel.EMAIL, new EmailDeliveryStrategy()],
      [NotificationChannel.SLACK, new SlackDeliveryStrategy()],
      [NotificationChannel.IN_APP, new InAppDeliveryStrategy()],
    ]);
    return new StrategyDeliveryDispatcher(deliveryStrategies);
  },
};

const rendererServiceProvider: Provider = {
  provide: NotificationRendererService,
  useFactory: (renderer: HandlebarsTemplateRenderer) => {
    return new NotificationRendererService(renderer);
  },
  inject: [HandlebarsTemplateRenderer],
};

const dispatchUseCaseProvider: Provider = {
  provide: DispatchNotificationUseCase,
  useFactory: (
    repo: ITemplateRepository,
    delivery: IDeliveryService,
    rendererService: NotificationRendererService,
  ) => {
    return new DispatchNotificationUseCase(repo, delivery, rendererService);
  },
  inject: ['ITemplateRepository', 'IDeliveryService', NotificationRendererService],
};

@Module({
  controllers: [NotificationController],
  providers: [
    repoProvider,
    rendererProvider,
    deliveryServiceProvider,
    rendererServiceProvider,
    dispatchUseCaseProvider,
  ],
})
export class NotificationModule {}
