/* eslint-disable */
import {
  Inject,
  Injectable,
  Logger,
  OnApplicationBootstrap,
  OnApplicationShutdown,
} from '@nestjs/common';
import { Client } from 'pg';
import { ProcessControlPlaneOutboxEventUseCase } from '../../../application/use-cases/process-control-plane-outbox-event.use-case.js';
import {
  EVENT_PUBLISHER,
  type IEventPublisher,
} from '../../../ports/outbound/event-publisher.port.js';

@Injectable()
export class ControlPlaneOutboxListenerAdapter
  implements OnApplicationBootstrap, OnApplicationShutdown
{
  private readonly logger = new Logger(ControlPlaneOutboxListenerAdapter.name);
  private client: Client;

  constructor(private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error('DATABASE_URL is not set');
    }
    this.client = new Client({ connectionString });
  }

  async onApplicationBootstrap() {
    await this.client.connect();

    this.client.on('notification', async (msg: any) => {
      if (msg.channel === 'control_plane_outbox_channel') {
        const eventId = msg.payload;
        this.logger.log(`Received outbox event notification for id: ${eventId}`);
        if (eventId) {
          try {
            await this.outboxProcessor.execute(eventId);
          } catch (e) {
            this.logger.error(`Failed to process event ${eventId}`, e);
          }
        }
      }
    });

    await this.client.query('LISTEN control_plane_outbox_channel');
    this.logger.log('Started listening on control_plane_outbox_channel');
  }

  async onApplicationShutdown() {
    await this.client.end();
  }
}
