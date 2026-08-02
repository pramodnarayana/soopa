import { UcpEventType } from '@soopa/schemas';
import { DomainEvent } from './domain.event.js';

export class AppUnsubscribedEvent implements DomainEvent {
  public readonly eventName = UcpEventType.APP_UNSUBSCRIBED;
  public readonly occurredOn = new Date();
  public readonly payload: Record<string, unknown>;

  constructor(
    public readonly tenantId: string,
    public readonly appSlug: string,
  ) {
    this.payload = { tenantId, appSlug };
  }
}
