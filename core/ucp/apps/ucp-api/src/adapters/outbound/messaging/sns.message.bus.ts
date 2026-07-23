import { Injectable, Logger } from '@nestjs/common';
import { SNSClient, PublishCommand } from '@aws-sdk/client-sns';
import { IMessageBus } from '../../../ports/outbound/message.bus';

@Injectable()
export class SnsMessageBusAdapter implements IMessageBus {
  private readonly snsClient: SNSClient;
  private readonly logger = new Logger(SnsMessageBusAdapter.name);

  constructor() {
    this.snsClient = new SNSClient({
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
    // Expect the topic argument to be a fully qualified ARN from the environment
    const topicArn = topic;

    this.logger.debug(`Publishing to SNS Topic: ${topicArn}`);

    try {
      await this.snsClient.send(
        new PublishCommand({
          TopicArn: topicArn,
          Message: JSON.stringify(message),
          MessageGroupId: groupId,
          MessageDeduplicationId: deduplicationId,
        }),
      );
      this.logger.debug(`Successfully published to ${topicArn}`);
    } catch (error) {
      this.logger.error(`Failed to publish to SNS ${topicArn}`, error);
      throw error;
    }
  }
}
