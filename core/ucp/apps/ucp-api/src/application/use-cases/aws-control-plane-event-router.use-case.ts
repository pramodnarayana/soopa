/* eslint-disable */

import { PublishCommand, SNSClient } from '@aws-sdk/client-sns';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ConfigKey } from '../../domain/enums/config-keys.enum.js';
import { DATABASE_CLIENT } from '../../infrastructure/database.constants.js';
import {
  APP_SUBSCRIPTION_REPOSITORY,
  type IAppSubscriptionRepository,
} from '../../ports/outbound/app-subscription.repository.js';
import { IControlPlaneEventRouter } from '../../ports/outbound/control-plane-event-router.port.js';

@Injectable()
export class AwsControlPlaneEventRouterUseCase implements IControlPlaneEventRouter {
  private readonly logger = new Logger(AwsControlPlaneEventRouterUseCase.name);
  private snsClient: SNSClient;
  private topicArn: string | undefined;

  constructor(
    @Inject(APP_SUBSCRIPTION_REPOSITORY)
    private readonly appSubscriptionRepo: IAppSubscriptionRepository,
    private readonly configService: ConfigService,
  ) {
    this.snsClient = new SNSClient({
      region: this.configService.get<string>('AWS_REGION') || 'us-east-1',
      endpoint:
        process.env.NODE_ENV !== 'production'
          ? 'http://sns.us-east-1.localhost.localstack.cloud:4566'
          : undefined,
    });
    this.topicArn =
      this.configService.get<string>(ConfigKey.SNS_TENANT_EVENTS_TOPIC_ARN) ||
      (process.env.NODE_ENV !== 'production'
        ? 'arn:aws:sns:us-east-1:000000000000:ucp-events.fifo'
        : undefined);
  }

  async route(event: {
    id: string;
    tenantId: string | null;
    eventType: string;
    payload: any;
  }): Promise<void> {
    if (!this.topicArn) {
      this.logger.error('SNS_TENANT_EVENTS_TOPIC_ARN is not configured');
      return;
    }

    if (!event.tenantId) {
      this.logger.warn(`Event ${event.id} has no tenantId, skipping Data Plane Routing.`);
      return;
    }

    // 1. Resolve which apps this tenant is subscribed to
    const subscribedAppSlugs = await this.appSubscriptionRepo.getActiveAppSlugsForTenant(
      event.tenantId,
    );
    if (subscribedAppSlugs.length === 0) {
      this.logger.debug(`Tenant ${event.tenantId} has no active subscriptions. Dropping event.`);
      return;
    }

    // 2. Dispatch to SNS with filter attributes
    // Conform to the enterprise-grade EventMessage schema which requires a nested payload
    const eventMessage = {
      idempotencyKey: event.id,
      tenantId: event.tenantId,
      eventType: event.eventType,
      payload: event.payload,
    };

    const command = new PublishCommand({
      TopicArn: this.topicArn,
      Message: JSON.stringify(eventMessage),
      MessageGroupId: event.tenantId,
      MessageDeduplicationId: event.id, // Ensure deduplication
      MessageAttributes: {
        'App-Targets': {
          DataType: 'String.Array',
          StringValue: JSON.stringify(subscribedAppSlugs), // e.g. '["edi", "idp"]'
        },
      },
    });

    try {
      const response = await this.snsClient.send(command);
      this.logger.log(
        `Published event ${event.id} to SNS (MessageId: ${response.MessageId}) with App-Targets: ${JSON.stringify(subscribedAppSlugs)}`,
      );
    } catch (error) {
      this.logger.error(`Failed to publish event ${event.id} to SNS`, error);
      throw error;
    }
  }
}
