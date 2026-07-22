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
