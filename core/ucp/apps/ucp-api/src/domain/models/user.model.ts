import { AggregateRoot } from './aggregate-root.js';

export class User extends AggregateRoot {
  constructor(
    public readonly id: string,
    public readonly idpUserId: string | null,
    public readonly email: string,
    public name: string,
    public status: 'active' | 'inactive',
    public readonly createdAt: Date,
    public updatedAt: Date,
  ) {
    super();
  }

  activate() {
    if (this.status !== 'active') {
      this.status = 'active';
      this.updatedAt = new Date();
    }
  }

  deactivate() {
    if (this.status !== 'inactive') {
      this.status = 'inactive';
      this.updatedAt = new Date();
    }
  }
}
