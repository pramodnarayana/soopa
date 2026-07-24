import {
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  InternalServerErrorException,
  Logger,
  Post,
  UsePipes,
  ValidationPipe,
} from '@nestjs/common';
import { IsArray, IsNotEmpty, IsObject, IsString } from 'class-validator';
import { DispatchNotificationUseCase } from '../application/DispatchNotificationUseCase.js';
import { Channel, NotificationEvent } from '../domain/models.js';

export class NotificationEventPayload {
  @IsString()
  @IsNotEmpty()
  tenantId!: string;

  @IsString()
  @IsNotEmpty()
  eventType!: string;

  @IsArray()
  channels!: Channel[];

  @IsObject()
  data!: Record<string, unknown>;
}

@Controller('api/v1/notifications')
@UsePipes(new ValidationPipe({ whitelist: true }))
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
        payload.data,
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
