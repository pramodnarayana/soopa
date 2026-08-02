import { Injectable, Logger, OnApplicationBootstrap, OnApplicationShutdown } from '@nestjs/common';
import { Client, type Notification } from 'pg';
import { ProcessControlPlaneOutboxEventUseCase } from '../../../application/use-cases/process-control-plane-outbox-event.use-case.js';

@Injectable()
export class ControlPlaneOutboxListenerAdapter
  implements OnApplicationBootstrap, OnApplicationShutdown
{
  private readonly logger = new Logger(ControlPlaneOutboxListenerAdapter.name);
  private client: Client;
  private isShuttingDown = false;
  private isReconnecting = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private readonly baseBackoffMs = 1000;
  private isHealthy = true;

  constructor(private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error('DATABASE_URL is not set');
    }
    this.client = new Client({ connectionString });
  }

  async onApplicationBootstrap() {
    await this.connect();
  }

  async onApplicationShutdown() {
    this.isShuttingDown = true;
    await this.client.end();
  }

  getHealth(): boolean {
    return this.isHealthy;
  }

  private async connect() {
    try {
      await this.client.connect();
      this.reconnectAttempts = 0;

      // Register error listener to prevent unhandled EventEmitter errors
      this.client.on('error', (err: Error) => {
        this.logger.error('PostgreSQL client error', err);
        if (!this.isShuttingDown) {
          this.handleDisconnect();
        }
      });

      // Register end listener to detect disconnections
      this.client.on('end', () => {
        this.logger.warn('PostgreSQL connection ended');
        if (!this.isShuttingDown) {
          this.handleDisconnect();
        }
      });

      this.client.on('notification', (msg: Notification) => {
        if (msg.channel === 'control_plane_outbox_channel') {
          const eventId = msg.payload as string;
          this.logger.log(`Received outbox event notification for id: ${eventId}`);
          if (eventId) {
            this.outboxProcessor.execute(eventId).catch((e) => {
              this.logger.error(`Failed to process event ${eventId}`, e);
            });
          }
        }
      });

      await this.client.query('LISTEN control_plane_outbox_channel');
      this.logger.log('Started listening on control_plane_outbox_channel');
    } catch (error) {
      this.logger.error('Failed to connect to PostgreSQL', error);
      if (!this.isShuttingDown) {
        this.handleDisconnect();
      }
    }
  }

  private handleDisconnect() {
    if (this.isReconnecting || this.isShuttingDown) {
      return;
    }

    this.isReconnecting = true;
    this.reconnectAttempts++;

    if (this.reconnectAttempts > this.maxReconnectAttempts) {
      this.logger.error(
        `Max reconnection attempts (${this.maxReconnectAttempts}) reached. Giving up.`,
      );
      this.isHealthy = false;
      this.isReconnecting = false;
      return;
    }

    const backoffMs = this.baseBackoffMs * Math.pow(2, this.reconnectAttempts - 1);
    this.logger.log(
      `Reconnecting to PostgreSQL in ${backoffMs}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
    );

    setTimeout(() => {
      void (async () => {
        // Clean up the old client before replacing it
        try {
          this.client.removeAllListeners();
          await this.client.end().catch(() => {
            // Ignore errors on cleanup of failed client
          });
        } catch {
          // Ignore cleanup errors
        }

        this.client = new Client({
          connectionString: process.env.DATABASE_URL,
        });

        try {
          await this.connect();
        } catch (error) {
          this.logger.error('Failed to reconnect to PostgreSQL', error);
          this.isReconnecting = false;
          this.handleDisconnect();
        }
      })();
    }, backoffMs);
  }
}
