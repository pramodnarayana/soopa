export class IdentityInfrastructureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'IdentityInfrastructureError';
  }
}

export class TenantMappingDomainError extends Error {
  constructor(email: string) {
    super(`User ${email} exists but is not mapped to any tenant in the UCP Database.`);
    this.name = 'TenantMappingDomainError';
  }
}

export class MissingIdentityTenantError extends Error {
  public readonly email?: string;

  constructor(email: string) {
    super('Missing Zitadel Organization ID');
    this.name = 'MissingIdentityTenantError';
    this.email = email;
  }
}

export class MissingUserDomainError extends Error {
  constructor(idpUserId: string) {
    super(
      `User with IdP ID ${idpUserId} not found. Account is still being provisioned or user does not exist.`,
    );
    this.name = 'MissingUserDomainError';
  }
}
