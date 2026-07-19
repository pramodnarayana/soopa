import { FastifyInstance } from 'fastify';
import { NotificationEvent, Channel } from '../domain/models.js';
import { DispatchNotificationUseCase } from '../application/DispatchNotificationUseCase.js';

interface NotificationEventPayload {
  tenantId: string;
  eventType: string;
  channels: Channel[];
  data: Record<string, unknown>;
}

export default function notificationRoutes(
  fastify: FastifyInstance,
  useCase: DispatchNotificationUseCase
) {
  fastify.post('/api/v1/notifications/send', async (request, reply) => {
    const payload = request.body as NotificationEventPayload;
    
    try {
      fastify.log.info({ eventType: payload.eventType }, 'Received notification dispatch request');
      
      // 1. Map HTTP request to Domain Model
      const event = new NotificationEvent(
        payload.tenantId,
        payload.eventType,
        payload.channels,
        payload.data
      );

      // 2. Delegate to Application Layer
      await useCase.execute(event);

      return reply.status(200).send({ status: 'ACCEPTED' });
    } catch (error) {
      fastify.log.error(error, 'Failed to dispatch notification');
      return reply.status(500).send({ error: (error as Error).message });
    }
  });
}
