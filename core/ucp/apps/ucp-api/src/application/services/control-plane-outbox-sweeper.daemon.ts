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
  private readonly batchLimit: number;
  private readonly cronInterval: string;

  constructor(
    @Inject(OUTBOX_REPOSITORY)
    private readonly outboxRepo: IControlPlaneOutboxRepository,
    private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase,
    private readonly configService: ConfigService,
  ) {
    this.batchLimit = this.configService.get<number>('OUTBOX_SWEEPER_BATCH_LIMIT') || 50;
    this.cronInterval =
      this.configService.get<string>('OUTBOX_SWEEPER_CRON_INTERVAL') ||
      CronExpression.EVERY_10_SECONDS;
  }

  @Cron(CronExpression.EVERY_10_SECONDS)
  async handleCron() {
    this.logger.debug('Replicating pending events to data planes...');

    // 1. Fetch pending events
    const pendingEvents = await this.outboxRepo.fetchPendingEvents(this.batchLimit);

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
