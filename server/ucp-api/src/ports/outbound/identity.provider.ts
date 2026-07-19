export const IDENTITY_PROVIDER = Symbol('IDENTITY_PROVIDER');

export interface IIdentityProvider {
  createOrganization(name: string): Promise<{ orgId: string }>;
}
