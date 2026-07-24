import { InternalServerErrorException } from '@nestjs/common';
import { NotificationChannel } from '@soopa/database';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NotificationController } from '../src/api/NotificationController.js';
import { DispatchNotificationUseCase } from '../src/application/DispatchNotificationUseCase.js';
import { NotificationEvent } from '../src/domain/models.js';

describe('NotificationController', () => {
  let controller: NotificationController;
  let useCase: DispatchNotificationUseCase;

  beforeEach(() => {
    vi.clearAllMocks();
    useCase = { execute: vi.fn() } as unknown as DispatchNotificationUseCase;
    controller = new NotificationController(useCase);
  });

  it('should accept a valid notification request', async () => {
    vi.spyOn(useCase, 'execute').mockResolvedValue();

    const payload = {
      tenantId: 't1',
      eventType: 'USER_SIGNED_UP',
      channels: [NotificationChannel.EMAIL],
      data: { userId: '123' },
    };

    const response = await controller.sendNotification(payload);

    expect(response.status).toBe('ACCEPTED');
    const executeSpy = vi.spyOn(useCase, 'execute');
    expect(executeSpy).toHaveBeenCalledWith(expect.any(NotificationEvent));
  });

  it('should throw InternalServerErrorException on use case error', async () => {
    vi.spyOn(useCase, 'execute').mockRejectedValue(new Error('Internal DB failure'));

    const payload = {
      tenantId: 't1',
      eventType: 'USER_SIGNED_UP',
      channels: [NotificationChannel.EMAIL],
      data: { userId: '123' },
    };

    await expect(controller.sendNotification(payload)).rejects.toThrow(
      InternalServerErrorException,
    );
  });
});
