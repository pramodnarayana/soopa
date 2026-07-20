import { Injectable } from '@nestjs/common';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';
import { IMessageBus } from '../../../ports/outbound/message.bus';

@Injectable()
export class SqsMessageBusAdapter implements IMessageBus {
  private readonly sqsClient: SQSClient;

  constructor() {
    this.sqsClient = new SQSClient({
      endpoint: process.env.AWS_ENDPOINT_URL || 'http://localhost:4566',
      region: process.env.AWS_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.AWS_ACCESS_KEY_ID || 'test',
        secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY || 'test',
      },
    });
  }

  async publish(
    topic: string,
    message: unknown,
    groupId?: string,
    deduplicationId?: string,
  ): Promise<void> {
    const queueUrl =
      process.env.EDI_PROVISIONING_QUEUE_URL ||
      'http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-provisioning.fifo';

    await this.sqsClient.send(
      new SendMessageCommand({
        QueueUrl: queueUrl, // In a real app, map the 'topic' string to the correct queue URL
        MessageBody: JSON.stringify(message),
        MessageGroupId: groupId,
        MessageDeduplicationId: deduplicationId,
      }),
    );
  }
}
