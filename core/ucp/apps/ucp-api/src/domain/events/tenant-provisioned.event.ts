import { DomainEvent } from './domain.event';
import { EventType } from '@soopa/schemas';

export class TenantProvisionedEvent implements DomainEvent {
  public readonly eventName = EventType.TENANT_PROVISIONED;
  public readonly occurredOn: Date;
  public readonly payload: Record<string, unknown>;

  constructor(tenantId: string, name: string, appSlugs: string[]) {
    this.occurredOn = new Date();
    this.payload = { tenantId, name, appSlugs };
  }
}
