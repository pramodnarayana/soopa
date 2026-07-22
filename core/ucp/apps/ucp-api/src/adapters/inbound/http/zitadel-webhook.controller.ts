import {
  Controller,
  Post,
  Body,
  Inject,
  HttpCode,
  HttpStatus,
  Logger,
  UnauthorizedException,
  Req,
} from '@nestjs/common';
import type { Request } from 'express';
import { USER_REPOSITORY } from '../../../ports/outbound/user.repository';
import type { IUserRepository } from '../../../ports/outbound/user.repository';

export class ZitadelWebhookPayload {
  eventType:
    | 'user.added'
    | 'user.changed'
    | 'user.removed'
    | 'user.membership.added'
    | 'user.membership.removed'
    | 'user.membership.changed';
  userId: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  tenantId?: string;
  role?: string;
}

@Controller('webhooks/zitadel')
export class ZitadelWebhookController {
  private readonly logger = new Logger(ZitadelWebhookController.name);

  constructor(
    @Inject(USER_REPOSITORY) private readonly userRepo: IUserRepository,
  ) {}

  @Post()
  @HttpCode(HttpStatus.OK)
  async handleWebhook(
    @Body() payload: ZitadelWebhookPayload,
    @Req() request: Request,
  ) {
    // Verify webhook authenticity
    // TODO: Implement proper webhook signature verification based on Zitadel's webhook security mechanism
    // For now, we validate that the webhook secret token is present in the header
    const webhookSecret = process.env.ZITADEL_WEBHOOK_SECRET;

    if (!webhookSecret) {
      if (process.env.NODE_ENV === 'development') {
        this.logger.warn(
          'ZITADEL_WEBHOOK_SECRET not configured - webhook authentication is disabled. This should only happen in development.',
        );
      } else {
        throw new UnauthorizedException(
          'Webhook secret is not configured in production environment',
        );
      }
    } else {
      const authHeader = request.headers['authorization'];
      const xWebhookSecret = request.headers['x-webhook-secret'];

      const isValid =
        authHeader === `Bearer ${webhookSecret}` ||
        xWebhookSecret === webhookSecret;

      if (!isValid) {
        this.logger.warn(
          'Webhook request rejected: Invalid or missing authentication',
        );
        throw new UnauthorizedException('Invalid webhook authentication');
      }
    }

    this.logger.log(
      `Received Zitadel Webhook: ${payload.eventType} for user ${payload.userId}`,
    );

    try {
      if (
        payload.eventType === 'user.added' ||
        payload.eventType === 'user.changed'
      ) {
        if (!payload.email || !payload.firstName) {
          this.logger.warn(
            `Skipping ${payload.eventType} for user ${payload.userId}: Missing required user profile fields`,
          );
          return { status: 'skipped' };
        }
        await this.userRepo.upsertUser({
          id: payload.userId,
          email: payload.email,
          name: `${payload.firstName} ${payload.lastName || ''}`.trim(),
        });
      }

      if (
        payload.eventType === 'user.membership.added' ||
        payload.eventType === 'user.membership.changed'
      ) {
        if (!payload.tenantId || !payload.role) {
          this.logger.warn(
            `Skipping ${payload.eventType} for user ${payload.userId}: Missing tenantId or role`,
          );
          return { status: 'skipped' };
        }
        await this.userRepo.upsertTenantUser({
          tenantId: payload.tenantId,
          userId: payload.userId,
          role: payload.role,
        });
      }

      if (payload.eventType === 'user.membership.removed') {
        if (!payload.tenantId) {
          this.logger.warn(
            `Skipping ${payload.eventType} for user ${payload.userId}: Missing tenantId`,
          );
          return { status: 'skipped' };
        }
        await this.userRepo.removeTenantUser(payload.tenantId, payload.userId);
      }

      // If user is completely removed, we might want to clean up tenantUsers then the user, but for now we rely on membership.removed
      if (payload.eventType === 'user.removed') {
        // Hard delete not strictly necessary if memberships are removed, but good practice
      }

      return { status: 'processed' };
    } catch (error) {
      this.logger.error(
        `Error processing webhook: ${(error as Error).message}`,
        (error as Error).stack,
      );
      // Throwing an error ensures Zitadel will retry the webhook delivery
      throw error;
    }
  }
}
