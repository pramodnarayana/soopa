import { Controller, Post, Body, HttpCode, HttpStatus, InternalServerErrorException, Logger } from '@nestjs/common';
import { DispatchNotificationUseCase } from '../application/DispatchNotificationUseCase.js';
import { NotificationEvent, Channel } from '../domain/models.js';

export interface NotificationEventPayload {
  tenantId: string;
  eventType: string;
  channels: Channel[];
  data: Record<string, unknown>;
}

@Controller('api/v1/notifications')
export class NotificationController {
  private readonly logger = new Logger(NotificationController.name);

  constructor(private readonly useCase: DispatchNotificationUseCase) {}

  @Post('send')
  @HttpCode(HttpStatus.ACCEPTED)
  async sendNotification(@Body() payload: NotificationEventPayload) {
    try {
      this.logger.log(`Received notification dispatch request for eventType: ${payload.eventType}`);
      
      const event = new NotificationEvent(
        payload.tenantId,
        payload.eventType,
        payload.channels,
        payload.data
      );

      await this.useCase.execute(event);

      return { status: 'ACCEPTED' };
    } catch (error) {
      if (error instanceof Error) {
        this.logger.error(`Failed to dispatch notification: ${error.message}`, error.stack);
        throw new InternalServerErrorException(error.message);
      }
      const errObj = typeof error === 'string' ? error : 'Unknown error';
      this.logger.error(`Failed to dispatch notification: ${errObj}`);
      throw new InternalServerErrorException(errObj);
    }
  }
}
