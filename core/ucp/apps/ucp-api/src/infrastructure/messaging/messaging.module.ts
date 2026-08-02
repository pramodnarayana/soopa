/* eslint-disable */
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { EventEmitterModule } from '@nestjs/event-emitter';
import { ControlPlaneOutboxListenerAdapter } from '../../adapters/inbound/database/control-plane-outbox-listener.adapter.js';
import { AwsSqsUcpControlPlaneConsumer } from '../../adapters/inbound/events/aws-sqs-ucp-control-plane-consumer.js';
import { ApplicationModule } from '../../application/application.module.js';
import { AwsControlPlaneEventRouterUseCase } from '../../application/use-cases/aws-control-plane-event-router.use-case.js';
import { InternalControlPlaneEventRouterUseCase } from '../../application/use-cases/internal-control-plane-event-router.use-case.js';
import { ProcessControlPlaneOutboxEventUseCase } from '../../application/use-cases/process-control-plane-outbox-event.use-case.js';
import { CONTROL_PLANE_EVENT_ROUTER } from '../../ports/outbound/control-plane-event-router.port.js';
import { DatabaseModule } from '../database.module.js';

const mode = process.env.CONTROL_PLANE_SYNC_MODE || 'internal';

const messagingProviders =
  mode === 'aws'
    ? [
        {
          provide: CONTROL_PLANE_EVENT_ROUTER,
          useClass: AwsControlPlaneEventRouterUseCase,
        },
        AwsSqsUcpControlPlaneConsumer,
        ControlPlaneOutboxListenerAdapter, // Always listens to UCP DB to push to SNS
        ProcessControlPlaneOutboxEventUseCase,
      ]
    : [
        {
          provide: CONTROL_PLANE_EVENT_ROUTER,
          useClass: InternalControlPlaneEventRouterUseCase,
        },
        ControlPlaneOutboxListenerAdapter, // Always listens to UCP DB to push to EDI/IDP DB
        ProcessControlPlaneOutboxEventUseCase,
      ];

@Module({
  imports: [ConfigModule, ApplicationModule, EventEmitterModule.forRoot()],
  providers: [...messagingProviders],
  exports: [...messagingProviders],
})
export class MessagingModule {}
