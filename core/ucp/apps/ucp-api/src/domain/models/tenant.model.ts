import { TenantProvisionedEvent } from '../events/tenant-provisioned.event.js';
import { AppSubscribedEvent } from '../events/app-subscribed.event.js';
import { AppUnsubscribedEvent } from '../events/app-unsubscribed.event.js';
import { AggregateRoot } from './aggregate-root.js';

export class Tenant extends AggregateRoot {
  constructor(
    public readonly id: string,
    public name: string,
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
    idpTenantId: string | null,
    subscriptions: string[] = [],
  ): Tenant {
    const now = new Date();
    const tenant = new Tenant(
      id,
      name,
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

  subscribe(appSlug: string) {
    if (this.status !== 'active') {
      throw new Error(
        'DomainException: Cannot subscribe inactive tenant to app',
      );
    }
    if (this.subscriptions.includes(appSlug)) {
      throw new Error(
        `DomainException: Tenant is already subscribed to ${appSlug}`,
      );
    }
    this.subscriptions.push(appSlug);
    this.updatedAt = new Date();
    this.addDomainEvent(new AppSubscribedEvent(this.id, this.name, appSlug));
  }

  unsubscribeFromApp(appSlug: string): void {
    const index = this.subscriptions.indexOf(appSlug);
    if (index > -1) {
      this.subscriptions.splice(index, 1);
      this.updatedAt = new Date();
      this.addDomainEvent(new AppUnsubscribedEvent(this.id, appSlug));
    } else {
      throw new Error(
        `DomainException: Tenant is not subscribed to ${appSlug}`,
      );
    }
  }

  changeStatus(newStatus: 'active' | 'inactive') {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.updatedAt = new Date();
    }
  }
}
