import { Injectable, Inject, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import {
  OUTBOX_REPOSITORY,
  type IOutboxRepository,
} from '../../ports/outbound/outbox.repository';
import {
  MESSAGE_BUS,
  type IMessageBus,
} from '../../ports/outbound/message.bus';

@Injectable()
export class OutboxSweeperService {
  private readonly logger = new Logger(OutboxSweeperService.name);

  constructor(
    @Inject(OUTBOX_REPOSITORY) private readonly outboxRepo: IOutboxRepository,
    @Inject(MESSAGE_BUS) private readonly messageBus: IMessageBus,
  ) {}

  @Cron(CronExpression.EVERY_10_SECONDS)
  async handleCron() {
    this.logger.debug('Sweeping outbox for pending events...');

    // 1. Fetch pending events
    const pendingEvents = await this.outboxRepo.fetchPendingEvents(50);

    if (pendingEvents.length === 0) {
      return;
    }

    this.logger.log(`Found ${pendingEvents.length} pending events.`);

    for (const event of pendingEvents) {
      try {
        // 2. Dispatch to Message Bus
        this.logger.log(
          `Dispatching event ${event.eventType} to message bus...`,
        );

        // Topic is hardcoded for EDI provisioning for now.
        await this.messageBus.publish(
          'edi-provisioning',
          event.payload,
          event.tenantId,
          event.idempotencyKey,
        );

        // 3. Mark as PROCESSED
        await this.outboxRepo.markAsProcessed(event.id);

        this.logger.log(`Event ${event.id} marked as PROCESSED.`);
      } catch (error: any) {
        this.logger.error(`Failed to process event ${event.id}`, error);
        await this.outboxRepo.markAsFailed(
          event.id,
          error?.message || 'Unknown error',
        );
      }
    }
  }
}
