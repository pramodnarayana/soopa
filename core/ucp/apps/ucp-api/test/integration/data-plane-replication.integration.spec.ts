import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DataPlaneReplicationService } from '../../src/application/services/data-plane-replication.service.js';
import { ConfigKey } from '../../src/domain/enums/config-keys.enum.js';
import { MESSAGE_BUS } from '../../src/ports/outbound/message.bus.js';
import {
  OUTBOX_REPOSITORY,
  OutboxEvent,
} from '../../src/ports/outbound/outbox.repository.js';

describe('DataPlaneReplicationService (Integration)', () => {
  let service: DataPlaneReplicationService;

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

  interface PublishedMessage {
    topic: string;
    message: unknown;
    groupId?: string;
    deduplicationId?: string;
  }
  let publishedMessages: PublishedMessage[] = [];
  let processedEventIds: string[] = [];

  beforeEach(async () => {
    publishedMessages = [];
    processedEventIds = [];

    const module: TestingModule = await Test.createTestingModule({
      providers: [
        DataPlaneReplicationService,
        {
          provide: OUTBOX_REPOSITORY,
          useValue: {
            fetchPendingEvents: () =>
              Promise.resolve(mockEvents.filter((e) => e.status === 'PENDING')),
            markAsProcessed: (id: string) => {
              processedEventIds.push(id);
              const event = mockEvents.find((e) => e.id === id);
              if (event) event.status = 'PROCESSED';
              return Promise.resolve();
            },
            markAsFailed: () => Promise.resolve(),
          },
        },
        {
          provide: MESSAGE_BUS,
          useValue: {
            publish: async (
              topic: string,
              message: unknown,
              groupId?: string,
              deduplicationId?: string,
            ) => {
              publishedMessages.push({
                topic,
                message,
                groupId,
                deduplicationId,
              });
              return Promise.resolve();
            },
          },
        },
        {
          provide: ConfigService,
          useValue: {
            getOrThrow: (key: ConfigKey | string) => {
              if (key === (ConfigKey.SNS_TENANT_EVENTS_TOPIC_ARN as string))
                return 'ucp.tenant.events.fifo';
              throw new Error(`Config key ${key} not found`);
            },
          },
        },
      ],
    }).compile();

    service = module.get<DataPlaneReplicationService>(
      DataPlaneReplicationService,
    );

    // Reset mock data status for isolation
    mockEvents[0].status = 'PENDING';
  });

  it('should fetch pending events, publish them, and mark them as PROCESSED', async () => {
    // Act
    await service.handleCron();

    // Assert
    expect(publishedMessages.length).toBe(1);
    expect(publishedMessages[0].topic).toBe('ucp.tenant.events.fifo');
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
