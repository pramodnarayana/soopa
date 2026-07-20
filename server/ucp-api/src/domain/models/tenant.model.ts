import { AggregateRoot } from './aggregate-root';
import { TenantProvisionedEvent } from '../events/tenant-provisioned.event';

export class Tenant extends AggregateRoot {
  constructor(
    public readonly id: string,
    public readonly name: string,
    public readonly zitadelOrgId: string | null,
    public readonly createdAt: Date,
    public readonly updatedAt: Date,
    public readonly subscriptions: string[] = [],
  ) {
    super();
  }

  static create(
    id: string,
    name: string,
    zitadelOrgId: string | null,
    subscriptions: string[] = [],
  ): Tenant {
    const now = new Date();
    const tenant = new Tenant(id, name, zitadelOrgId, now, now, subscriptions);

    tenant.addDomainEvent(new TenantProvisionedEvent(id, name, subscriptions));

    return tenant;
  }
}
