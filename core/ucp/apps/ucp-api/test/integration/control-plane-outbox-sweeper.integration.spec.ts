import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlPlaneOutboxSweeperDaemon } from '../../src/application/services/control-plane-outbox-sweeper.daemon.js';
import { ProcessControlPlaneOutboxEventUseCase } from '../../src/application/use-cases/process-control-plane-outbox-event.use-case.js';
import {
  OUTBOX_REPOSITORY,
  OutboxEvent,
} from '../../src/ports/outbound/control-plane-outbox.repository.js';

describe('ControlPlaneOutboxSweeperDaemon', () => {
  let daemon: ControlPlaneOutboxSweeperDaemon;
  let useCaseExecuteSpy: ReturnType<typeof vi.fn>;

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

  beforeEach(async () => {
    useCaseExecuteSpy = vi.fn().mockResolvedValue(undefined);

    const module: TestingModule = await Test.createTestingModule({
      providers: [
        ControlPlaneOutboxSweeperDaemon,
        {
          provide: OUTBOX_REPOSITORY,
          useValue: {
            fetchPendingEvents: () =>
              Promise.resolve(mockEvents.filter((e) => e.status === 'PENDING')),
          },
        },
        {
          provide: ProcessControlPlaneOutboxEventUseCase,
          useValue: {
            execute: useCaseExecuteSpy,
          },
        },
        {
          provide: ConfigService,
          useValue: {
            get: vi.fn().mockReturnValue(undefined),
          },
        },
      ],
    }).compile();

    daemon = module.get<ControlPlaneOutboxSweeperDaemon>(ControlPlaneOutboxSweeperDaemon);

    mockEvents[0].status = 'PENDING';
  });

  it('should fetch pending events and execute the processor', async () => {
    await daemon.handleCron();
    expect(useCaseExecuteSpy).toHaveBeenCalledWith('event_123');
  });

  it('should not throw or crash when no events are pending', async () => {
    mockEvents[0].status = 'PROCESSED';
    await daemon.handleCron();
    expect(useCaseExecuteSpy).not.toHaveBeenCalled();
  });
});
