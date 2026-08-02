import { UcpEventType } from '@soopa/schemas';
import { DomainEvent } from './domain.event.js';

export class AppSubscribedEvent implements DomainEvent {
  public readonly eventName = UcpEventType.APP_SUBSCRIBED;
  public readonly occurredOn = new Date();
  public readonly payload: Record<string, unknown>;

  constructor(
    public readonly tenantId: string,
    public readonly tenantName: string,
    public readonly appSlug: string,
  ) {
    this.payload = { tenantId, tenantName, appSlug };
  }
}
