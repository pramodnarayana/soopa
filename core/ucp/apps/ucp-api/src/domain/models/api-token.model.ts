import * as crypto from 'crypto';
import { AggregateRoot } from './aggregate-root.js';

export class ApiToken extends AggregateRoot {
  constructor(
    public readonly id: string,
    public readonly tenantId: string,
    public readonly name: string,
    public readonly clientId: string,
    public readonly secretHash: string,
    public readonly active: boolean,
    public readonly createdAt: Date,
    public readonly lastUsedAt: Date | null = null,
    public readonly expiresAt: Date | null = null,
  ) {
    super();
  }

  static generate(
    tenantId: string,
    name: string,
    expiresAt?: Date,
  ): { apiToken: ApiToken; rawSecret: string } {
    const rawSecret = crypto.randomBytes(32).toString('hex');
    const secretHash = crypto.createHash('sha256').update(rawSecret).digest('hex');
    const clientId = `client_${crypto.randomBytes(12).toString('hex')}`;
    const id = `token_${crypto.randomBytes(12).toString('hex')}`;

    const apiToken = new ApiToken(
      id,
      tenantId,
      name,
      clientId,
      secretHash,
      true,
      new Date(),
      null,
      expiresAt || null,
    );

    return { apiToken, rawSecret };
  }

  update(props: { name?: string; active?: boolean }): ApiToken {
    return new ApiToken(
      this.id,
      this.tenantId,
      props.name !== undefined ? props.name : this.name,
      this.clientId,
      this.secretHash,
      props.active !== undefined ? props.active : this.active,
      this.createdAt,
      this.lastUsedAt,
      this.expiresAt,
    );
  }

  markAsUsed(): ApiToken {
    return new ApiToken(
      this.id,
      this.tenantId,
      this.name,
      this.clientId,
      this.secretHash,
      this.active,
      this.createdAt,
      new Date(),
      this.expiresAt,
    );
  }
}
