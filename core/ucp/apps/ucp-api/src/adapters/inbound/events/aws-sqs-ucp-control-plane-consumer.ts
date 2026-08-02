import {
  DeleteMessageCommand,
  type Message,
  ReceiveMessageCommand,
  SQSClient,
} from '@aws-sdk/client-sqs';
import { Injectable, Logger, OnApplicationBootstrap, OnApplicationShutdown } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ProcessControlPlaneOutboxEventUseCase } from '../../../application/use-cases/process-control-plane-outbox-event.use-case.js';

@Injectable()
export class AwsSqsUcpControlPlaneConsumer
  implements OnApplicationBootstrap, OnApplicationShutdown
{
  private readonly logger = new Logger(AwsSqsUcpControlPlaneConsumer.name);
  private sqsClient: SQSClient | undefined;
  private queueUrl: string | undefined;
  private isRunning = false;

  constructor(
    private readonly configService: ConfigService,
    private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase,
  ) {}

  onApplicationBootstrap() {
    this.queueUrl =
      this.configService.get<string>('SQS_UCP_EVENTS_QUEUE_URL') ||
      (process.env.NODE_ENV !== 'production'
        ? 'http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp-events.fifo'
        : undefined);

    // Fallback or early exit if not configured, although it should be if AWS is enabled
    if (!this.queueUrl) {
      this.logger.warn('SQS_UCP_EVENTS_QUEUE_URL is not set. AWS SQS Consumer will not start.');
      return;
    }

    this.sqsClient = new SQSClient({
      region: this.configService.get<string>('AWS_REGION') || 'us-east-1',
      endpoint: this.configService.get<string>('AWS_ENDPOINT_URL'),
    });

    this.isRunning = true;
    this.pollQueue().catch((err) => {
      this.logger.error('Unhandled error in SQS polling loop', err);
    });
  }

  onApplicationShutdown() {
    this.isRunning = false;
    this.sqsClient?.destroy();
  }

  private async pollQueue() {
    if (!this.sqsClient || !this.queueUrl) return;

    while (this.isRunning) {
      try {
        const command = new ReceiveMessageCommand({
          QueueUrl: this.queueUrl,
          MaxNumberOfMessages: 10,
          WaitTimeSeconds: 20, // Long polling
        });

        const response = await this.sqsClient.send(command);

        if (response.Messages && response.Messages.length > 0) {
          for (const message of response.Messages) {
            await this.processMessage(message);
          }
        }
      } catch (error: unknown) {
        // If it's a shutdown abort, ignore
        if (!this.isRunning) break;
        const err = error instanceof Error ? error : new Error(String(error));
        this.logger.error(`Error polling SQS queue: ${err.message}`, err.stack);
        // Sleep briefly to avoid tight error loops
        await new Promise((resolve) => setTimeout(resolve, 5000));
      }
    }
  }

  private async processMessage(message: Message) {
    if (!this.sqsClient || !this.queueUrl) return;

    try {
      this.logger.debug(`[AWS MESSAGE BUS] Received SQS message ${message.MessageId}`);

      let payload: unknown;
      try {
        payload = JSON.parse(message.Body ?? '{}');
      } catch (e) {
        this.logger.error(`Failed to parse SQS message body: ${message.Body}`);
        // If we can't parse it, it's a poison pill, delete it (or leave it for DLQ if we prefer)
        throw e;
      }

      // The event ID should be passed in the payload or retrieved from the outbox event payload
      // SQS messages from SNS wrap the message in an outer envelope.
      // E.g. SNS envelope has .Message string which contains our actual JSON payload.
      let actualEvent: Record<string, unknown>;
      if (
        payload &&
        typeof payload === 'object' &&
        'Type' in payload &&
        payload.Type === 'Notification' &&
        'Message' in payload &&
        typeof payload.Message === 'string'
      ) {
        actualEvent = JSON.parse(payload.Message) as Record<string, unknown>;
      } else {
        actualEvent = payload as Record<string, unknown>;
      }

      // Use actualEvent.id as the outbox event ID for both SNS-wrapped and direct messages
      const outboxEventId = actualEvent?.id as string | undefined;

      if (outboxEventId) {
        await this.outboxProcessor.execute(outboxEventId);
      } else {
        this.logger.error(
          `Invalid SQS message format. Missing event id: ${JSON.stringify(actualEvent)}`,
        );
        throw new Error('Missing event id');
      }

      // Delete message after successful processing
      await this.sqsClient.send(
        new DeleteMessageCommand({
          QueueUrl: this.queueUrl,
          ReceiptHandle: message.ReceiptHandle,
        }),
      );
      this.logger.debug(`[AWS MESSAGE BUS] Deleted message ${message.MessageId}`);
    } catch (error: unknown) {
      const err = error instanceof Error ? error : new Error(String(error));
      this.logger.error(
        `[AWS MESSAGE BUS] Failed to process message ${message.MessageId}: ${err.message}`,
        err.stack,
      );
      // Let it time out and go back to queue or DLQ
    }
  }
}
