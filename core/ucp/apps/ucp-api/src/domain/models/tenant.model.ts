import { TenantProvisionedEvent } from '../events/tenant-provisioned.event.js';
import { AggregateRoot } from './aggregate-root.js';

export class Tenant extends AggregateRoot {
  constructor(
    public readonly id: string,
    public name: string,
    public readonly zitadelOrgId: string | null,
    public readonly idpTenantId: string | null,
    public status: 'active' | 'inactive',
    public readonly createdAt: Date,
    public updatedAt: Date,
    public readonly subscriptions: string[] = [],
  ) {
    super();
  }

  static create(
    id: string,
    name: string,
    zitadelOrgId: string | null,
    idpTenantId: string | null,
    subscriptions: string[] = [],
  ): Tenant {
    const now = new Date();
    const tenant = new Tenant(
      id,
      name,
      zitadelOrgId,
      idpTenantId,
      'active',
      now,
      now,
      subscriptions,
    );

    tenant.addDomainEvent(new TenantProvisionedEvent(id, name, subscriptions));

    return tenant;
  }

  rename(newName: string) {
    if (!newName || newName.trim() === '') {
      throw new Error('DomainException: Tenant name cannot be empty');
    }
    this.name = newName.trim();
    this.updatedAt = new Date();
  }

  changeStatus(newStatus: 'active' | 'inactive') {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.updatedAt = new Date();
    }
  }
}
