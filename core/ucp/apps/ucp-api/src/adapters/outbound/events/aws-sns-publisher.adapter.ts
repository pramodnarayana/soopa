import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ConfigKey } from '../../../domain/enums/config-keys.enum.js';
import {
  type IControlPlaneOutboxRepository,
  OUTBOX_REPOSITORY,
} from '../../../ports/outbound/control-plane-outbox.repository.js';
import type { IEventPublisher } from '../../../ports/outbound/event-publisher.port.js';
import { type IMessageBus, MESSAGE_BUS } from '../../../ports/outbound/message.bus.js';

@Injectable()
export class AwsSnsPublisherAdapter implements IEventPublisher {
  private readonly logger = new Logger(AwsSnsPublisherAdapter.name);

  constructor(
    @Inject(MESSAGE_BUS) private readonly messageBus: IMessageBus,
    @Inject(OUTBOX_REPOSITORY)
    private readonly outboxRepo: IControlPlaneOutboxRepository,
    private readonly configService: ConfigService,
  ) {}

  async publish(eventId: string): Promise<void> {
    this.logger.debug(`[AWS MESSAGE BUS] Fetching event ${eventId} to emit to SNS...`);
    const event = await this.outboxRepo.findById(eventId);
    if (!event) {
      this.logger.warn(`Event ${eventId} not found in outbox, skipping SNS publish.`);
      return;
    }

    const topicArn =
      this.configService.get<string>(ConfigKey.SNS_TENANT_EVENTS_TOPIC_ARN) ||
      (process.env.NODE_ENV !== 'production'
        ? 'arn:aws:sns:us-east-1:000000000000:ucp-events.fifo'
        : undefined);

    if (!topicArn) {
      throw new Error('SNS_TENANT_EVENTS_TOPIC_ARN is not configured');
    }

    const messagePayload = {
      id: event.id,
      eventType: event.eventType,
      payload: event.payload,
    };

    await this.messageBus.publish(
      topicArn,
      messagePayload,
      event.tenantId || undefined,
      event.idempotencyKey,
    );
  }
}
