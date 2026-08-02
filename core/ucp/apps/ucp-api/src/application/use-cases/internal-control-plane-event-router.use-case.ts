import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  APP_SUBSCRIPTION_REPOSITORY,
  type IAppSubscriptionRepository,
} from '../../ports/outbound/app-subscription.repository.js';
import { IControlPlaneEventRouter } from '../../ports/outbound/control-plane-event-router.port.js';
import {
  type ITargetControlPlaneOutboxRepository,
  TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY,
} from '../../ports/outbound/target-control-plane-outbox.repository.js';

@Injectable()
export class InternalControlPlaneEventRouterUseCase implements IControlPlaneEventRouter {
  private readonly logger = new Logger(InternalControlPlaneEventRouterUseCase.name);

  constructor(
    @Inject(APP_SUBSCRIPTION_REPOSITORY)
    private readonly appSubscriptionRepo: IAppSubscriptionRepository,
    @Inject(TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY)
    private readonly targetOutboxRepo: ITargetControlPlaneOutboxRepository,
  ) {}

  async route(event: {
    id: string;
    tenantId: string | null;
    eventType: string;
    payload: Record<string, unknown>;
  }): Promise<void> {
    this.logger.debug(`Routing event ${event.eventType} via Internal Data Plane Router...`);

    // If event is not tenant-specific, or it is explicitly common (e.g., webhook),
    // we need to dynamically route it to active subscriptions.
    // For now, if no tenantId, we skip routing (this router is specifically for tenant configs)
    if (!event.tenantId) {
      this.logger.warn(`Event ${event.id} has no tenantId, skipping Data Plane Routing.`);
      return;
    }

    // 1. Resolve which apps this tenant is subscribed to
    const subscribedAppSlugs = await this.appSubscriptionRepo.getActiveAppSlugsForTenant(
      event.tenantId,
    );
    if (subscribedAppSlugs.length === 0) {
      this.logger.debug(`Tenant ${event.tenantId} has no active subscriptions. Dropping event.`);
      return;
    }

    // 2. Dispatch to specific Inboxes (Outboxes) based on the appSlug
    this.logger.log(
      `Tenant ${event.tenantId} subscribed to: ${subscribedAppSlugs.join(', ')}. Fan-out routing...`,
    );

    for (const appSlug of subscribedAppSlugs) {
      await this.targetOutboxRepo.publishToApp(appSlug, {
        id: event.id,
        tenantId: event.tenantId,
        eventType: event.eventType,
        payload: event.payload,
      });
    }
  }
}
