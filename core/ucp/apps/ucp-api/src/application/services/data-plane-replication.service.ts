import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cron, CronExpression } from '@nestjs/schedule';
import { ConfigKey } from '../../domain/enums/config-keys.enum.js';
import {
  type IMessageBus,
  MESSAGE_BUS,
} from '../../ports/outbound/message.bus.js';
import {
  type IOutboxRepository,
  OUTBOX_REPOSITORY,
} from '../../ports/outbound/outbox.repository.js';

@Injectable()
export class DataPlaneReplicationService {
  private readonly logger = new Logger(DataPlaneReplicationService.name);

  constructor(
    @Inject(OUTBOX_REPOSITORY) private readonly outboxRepo: IOutboxRepository,
    @Inject(MESSAGE_BUS) private readonly messageBus: IMessageBus,
    private readonly configService: ConfigService,
  ) {}

  @Cron(CronExpression.EVERY_10_SECONDS)
  async handleCron() {
    this.logger.debug('Replicating pending events to data planes...');

    // 1. Fetch pending events
    const pendingEvents = await this.outboxRepo.fetchPendingEvents(50);

    if (pendingEvents.length === 0) {
      return;
    }

    this.logger.log(`Found ${pendingEvents.length} pending events.`);

    // Resolve SNS topic ARN once before processing events
    const topicArn = this.configService.getOrThrow<string>(
      ConfigKey.SNS_TENANT_EVENTS_TOPIC_ARN,
    );

    for (const event of pendingEvents) {
      try {
        // 2. Dispatch to Message Bus
        this.logger.log(
          `Dispatching event ${event.eventType} to message bus...`,
        );

        // Dispatch to the SNS fan-out topic for all Data Planes
        await this.messageBus.publish(
          topicArn,
          event.payload,
          event.tenantId,
          event.idempotencyKey,
        );

        // 3. Mark as PROCESSED
        await this.outboxRepo.markAsProcessed(event.id);

        this.logger.log(`Event ${event.id} marked as PROCESSED.`);
      } catch (error: unknown) {
        this.logger.error(`Failed to process event ${event.id}`, error);
        const errorMessage =
          error instanceof Error ? error.message : String(error);
        await this.outboxRepo.markAsFailed(event.id, errorMessage);
      }
    }
  }
}
