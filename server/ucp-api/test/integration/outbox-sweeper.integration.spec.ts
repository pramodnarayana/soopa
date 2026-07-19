import { Test, TestingModule } from '@nestjs/testing';
import { OutboxSweeperService } from '../../src/application/services/outbox-sweeper.service';
import {
  OUTBOX_REPOSITORY,
  IOutboxRepository,
  OutboxEvent,
} from '../../src/ports/outbound/outbox.repository';
import { MESSAGE_BUS, IMessageBus } from '../../src/ports/outbound/message.bus';

describe('OutboxSweeperService (Integration)', () => {
  let service: OutboxSweeperService;

  // In-memory test doubles
  const mockEvents: OutboxEvent[] = [
    {
      id: 'event_123',
      idempotencyKey: 'idemp_123',
      tenantId: 'tenant_123',
      eventType: 'TENANT_PROVISIONED',
      payload: { foo: 'bar' },
      status: 'PENDING',
      createdAt: new Date(),
      updatedAt: new Date(),
    },
  ];

  let publishedMessages: any[] = [];
  let processedEventIds: string[] = [];

  beforeEach(async () => {
    publishedMessages = [];
    processedEventIds = [];

    const module: TestingModule = await Test.createTestingModule({
      providers: [
        OutboxSweeperService,
        {
          provide: OUTBOX_REPOSITORY,
          useValue: {
            fetchPendingEvents: async () => mockEvents.filter((e) => e.status === 'PENDING'),
            markAsProcessed: async (id: string) => {
              processedEventIds.push(id);
              const event = mockEvents.find((e) => e.id === id);
              if (event) event.status = 'PROCESSED';
            },
            markAsFailed: async () => {},
          } as IOutboxRepository,
        },
        {
          provide: MESSAGE_BUS,
          useValue: {
            publish: async (
              topic: string,
              message: any,
              groupId?: string,
              deduplicationId?: string,
            ) => {
              publishedMessages.push({
                topic,
                message,
                groupId,
                deduplicationId,
              });
            },
          } as IMessageBus,
        },
      ],
    }).compile();

    service = module.get<OutboxSweeperService>(OutboxSweeperService);

    // Reset mock data status for isolation
    mockEvents[0].status = 'PENDING';
  });

  it('should fetch pending events, publish them, and mark them as PROCESSED', async () => {
    // Act
    await service.handleCron();

    // Assert
    expect(publishedMessages.length).toBe(1);
    expect(publishedMessages[0].topic).toBe('edi-provisioning');
    expect(publishedMessages[0].message).toEqual({ foo: 'bar' });
    expect(publishedMessages[0].groupId).toBe('tenant_123');
    expect(publishedMessages[0].deduplicationId).toBe('idemp_123');

    expect(processedEventIds.length).toBe(1);
    expect(processedEventIds[0]).toBe('event_123');
  });

  it('should not throw or crash when no events are pending', async () => {
    // Arrange
    mockEvents[0].status = 'PROCESSED'; // No pending events

    // Act
    await service.handleCron();

    // Assert
    expect(publishedMessages.length).toBe(0);
  });
});
