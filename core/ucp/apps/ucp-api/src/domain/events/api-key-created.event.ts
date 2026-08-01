import { UcpEventType } from '@soopa/schemas';
import { DomainEvent } from './domain.event.js';

export class ApiKeyCreatedEvent implements DomainEvent {
  public readonly eventName = UcpEventType.API_KEY_CREATED;
  public readonly occurredOn = new Date();
  public readonly payload: Record<string, unknown>;

  constructor(
    public readonly id: string,
    public readonly tenantId: string,
    public readonly name: string,
    public readonly keyHash: string,
    public readonly scopes: string[],
  ) {
    this.payload = {
      id,
      tenantId,
      name,
      keyHash,
      scopes,
    };
  }
}
