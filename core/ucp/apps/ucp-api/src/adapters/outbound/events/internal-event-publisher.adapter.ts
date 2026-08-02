import { Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import type { IEventPublisher } from '../../../ports/outbound/event-publisher.port.js';

@Injectable()
export class InternalEventPublisherAdapter implements IEventPublisher {
  private readonly logger = new Logger(InternalEventPublisherAdapter.name);

  constructor(private readonly eventEmitter: EventEmitter2) {}

  async publish(eventId: string): Promise<void> {
    this.logger.log(`[INTERNAL MESSAGE BUS] Emitting internal outbox event...`);
    this.eventEmitter.emit('outbox.event.created', eventId);
    await Promise.resolve();
  }
}
