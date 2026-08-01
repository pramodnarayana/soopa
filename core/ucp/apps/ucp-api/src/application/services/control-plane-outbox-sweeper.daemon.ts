/* eslint-disable */
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cron, CronExpression } from '@nestjs/schedule';
import { ConfigKey } from '../../domain/enums/config-keys.enum.js';
import {
  type IControlPlaneOutboxRepository,
  OUTBOX_REPOSITORY,
} from '../../ports/outbound/control-plane-outbox.repository.js';
import { ProcessControlPlaneOutboxEventUseCase } from '../use-cases/process-control-plane-outbox-event.use-case.js';

@Injectable()
export class ControlPlaneOutboxSweeperDaemon {
  private readonly logger = new Logger(ControlPlaneOutboxSweeperDaemon.name);

  constructor(
    @Inject(OUTBOX_REPOSITORY)
    private readonly outboxRepo: IControlPlaneOutboxRepository,
    private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase,
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

    for (const event of pendingEvents) {
      try {
        await this.outboxProcessor.execute(event.id);
      } catch (error) {
        this.logger.error(`Failed to process event ${event.id}`, error);
      }
    }
  }
}
