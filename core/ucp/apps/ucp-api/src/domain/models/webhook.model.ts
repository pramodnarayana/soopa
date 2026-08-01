import { AggregateRoot } from './aggregate-root.js';

export class Webhook extends AggregateRoot {
  constructor(
    public readonly id: string,
    public readonly tenantId: string,
    public readonly name: string,
    public readonly url: string,
    public readonly authHeaderVaultRef: string | null,
    public readonly active: boolean,
    public readonly createdAt: Date,
    public readonly updatedAt: Date,
  ) {
    super();
  }

  static create(
    id: string,
    tenantId: string,
    name: string,
    url: string,
    authHeaderVaultRef: string | null,
  ): Webhook {
    const webhook = new Webhook(
      id,
      tenantId,
      name,
      url,
      authHeaderVaultRef,
      true,
      new Date(),
      new Date(),
    );
    webhook.addDomainEvent({
      eventName: 'webhook.created',
      occurredOn: new Date(),
      payload: { resource_id: id },
    });
    return webhook;
  }

  update(props: { name?: string; url?: string; active?: boolean }): Webhook {
    const webhook = new Webhook(
      this.id,
      this.tenantId,
      props.name !== undefined ? props.name : this.name,
      props.url !== undefined ? props.url : this.url,
      this.authHeaderVaultRef,
      props.active !== undefined ? props.active : this.active,
      this.createdAt,
      new Date(),
    );
    webhook.addDomainEvent({
      eventName: 'webhook.updated',
      occurredOn: new Date(),
      payload: { resource_id: this.id },
    });
    return webhook;
  }

  markDeleted(): void {
    this.addDomainEvent({
      eventName: 'webhook.deleted',
      occurredOn: new Date(),
      payload: { resource_id: this.id },
    });
  }
}
