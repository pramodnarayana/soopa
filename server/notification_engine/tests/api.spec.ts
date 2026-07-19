import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect, vi } from 'vitest';
import Fastify from 'fastify';
import notificationRoutes from '../src/api/routes.js';
import { DispatchNotificationUseCase } from '../src/application/DispatchNotificationUseCase.js';
import { NotificationEvent } from '../src/domain/models.js';

describe('Notification API Routes', () => {
  it('should accept notification request and call use case', async () => {
    const fastify = Fastify();
    
    const mockUseCase = {
      execute: vi.fn().mockResolvedValue(undefined)
    } as unknown as DispatchNotificationUseCase;

    notificationRoutes(fastify, mockUseCase);

    const response = await fastify.inject({
      method: 'POST',
      url: '/api/v1/notifications/send',
      payload: {
        tenantId: 't1',
        eventType: EventTypes.TEST,
        channels: [NotificationChannel.EMAIL],
        data: { a: 1 }
      }
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ status: 'ACCEPTED' });
    expect(mockUseCase.execute).toHaveBeenCalled();
    const event = (mockUseCase.execute as never).mock.calls[0][0] as NotificationEvent;
    expect(event.tenantId).toBe('t1');
    expect(event.eventType).toBe(EventTypes.TEST);
    expect(event.channels).toEqual([NotificationChannel.EMAIL]);
    expect(event.payload).toEqual({ a: 1 });
  });

  it('should return 500 on use case error', async () => {
    const fastify = Fastify();
    
    const mockUseCase = {
      execute: vi.fn().mockRejectedValue(new Error('Failed'))
    } as unknown as DispatchNotificationUseCase;

    notificationRoutes(fastify, mockUseCase);

    const response = await fastify.inject({
      method: 'POST',
      url: '/api/v1/notifications/send',
      payload: {
        tenantId: 't1',
        eventType: EventTypes.TEST,
        channels: [NotificationChannel.EMAIL],
        data: {}
      }
    });

    expect(response.statusCode).toBe(500);
    expect(response.json()).toEqual({ error: 'Failed' });
  });
});
