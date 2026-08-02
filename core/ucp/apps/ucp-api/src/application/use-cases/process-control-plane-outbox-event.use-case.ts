import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import type { DbClient } from '@soopa/database';
import { controlPlaneOutbox } from '@soopa/database';
import { eq } from 'drizzle-orm';
import {
  EventRoutingScope,
  getEventRoutingScope,
} from '../../domain/events/event-routing.policy.js';
import { DATABASE_CLIENT } from '../../infrastructure/database.constants.js';
import {
  CONTROL_PLANE_EVENT_ROUTER,
  type IControlPlaneEventRouter,
} from '../../ports/outbound/control-plane-event-router.port.js';
import {
  type IControlPlaneOutboxRepository,
  OUTBOX_REPOSITORY,
} from '../../ports/outbound/control-plane-outbox.repository.js';

@Injectable()
export class ProcessControlPlaneOutboxEventUseCase {
  private readonly logger = new Logger(ProcessControlPlaneOutboxEventUseCase.name);

  constructor(
    @Inject(DATABASE_CLIENT) private readonly db: DbClient,
    @Inject(OUTBOX_REPOSITORY)
    private readonly outboxRepo: IControlPlaneOutboxRepository,
    @Inject(CONTROL_PLANE_EVENT_ROUTER)
    private readonly eventRouter: IControlPlaneEventRouter,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  async execute(eventId: string): Promise<void> {
    // Phase 1: Load and lock the event in a short transaction
    const event = await this.db.transaction(async (tx) => {
      const [evt] = await tx
        .select()
        .from(controlPlaneOutbox)
        .where(eq(controlPlaneOutbox.id, eventId))
        .for('update'); // Ensure no other worker processes this simultaneously

      if (!evt) {
        this.logger.warn(`Event ${eventId} not found`);
        return null;
      }

      if (evt.status === 'PROCESSED') {
        this.logger.log(`Event ${eventId} is already processed.`);
        return null;
      }

      return evt;
    });

    if (!event) {
      return;
    }

    // --- ENTERPRISE EVENT ROUTING FILTER ---
    const routingScope = getEventRoutingScope(event.eventType);

    if (!routingScope) {
      this.logger.warn(
        `Unrecognized event type [${event.eventType}]. Marking as PROCESSED without routing.`,
      );
      await this.db
        .update(controlPlaneOutbox)
        .set({ status: 'PROCESSED', updatedAt: new Date() })
        .where(eq(controlPlaneOutbox.id, eventId));
      return;
    }

    // Phase 2: Perform delivery/routing outside the transaction (no DB lock held)
    try {
      if (routingScope === EventRoutingScope.INTERNAL) {
        // Dispatch internally to listeners (e.g. Shard Allocator)
        const listeners = this.eventEmitter.listeners(event.eventType);
        if (listeners.length > 0) {
          await this.eventEmitter.emitAsync(event.eventType, {
            payload: event.payload,
          });
        } else {
          this.logger.debug(`No internal listeners for internal event: ${event.eventType}.`);
        }
      }

      if (routingScope === EventRoutingScope.EXTERNAL_DATA_PLANE) {
        // Dispatch explicitly to the Data Plane Router
        await this.eventRouter.route({
          id: event.id,
          tenantId: event.tenantId,
          eventType: event.eventType,
          payload: event.payload as Record<string, unknown>,
        });
      }

      // Phase 3: Mark as PROCESSED in a new short transaction
      await this.db
        .update(controlPlaneOutbox)
        .set({ status: 'PROCESSED', updatedAt: new Date() })
        .where(eq(controlPlaneOutbox.id, eventId));
    } catch (error) {
      // Phase 3b: Mark as FAILED in a new short transaction
      this.logger.error(`Failed to process event ${eventId}`, error);
      await this.db
        .update(controlPlaneOutbox)
        .set({
          status: 'FAILED',
          errorReason: error instanceof Error ? error.message : 'Unknown error',
          updatedAt: new Date(),
        })
        .where(eq(controlPlaneOutbox.id, eventId));
    }
  }
}
