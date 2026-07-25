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

  update(props: { name?: string; url?: string; active?: boolean }): Webhook {
    return new Webhook(
      this.id,
      this.tenantId,
      props.name !== undefined ? props.name : this.name,
      props.url !== undefined ? props.url : this.url,
      this.authHeaderVaultRef,
      props.active !== undefined ? props.active : this.active,
      this.createdAt,
      new Date(),
    );
  }
}
