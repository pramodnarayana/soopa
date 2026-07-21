export const ORGANIZATION_PROVIDER = Symbol('ORGANIZATION_PROVIDER');

export interface IOrganizationProvider {
  createOrganization(
    name: string,
  ): Promise<{ orgId: string; grantSucceeded?: boolean }>;
  deleteOrganization(orgId: string): Promise<void>;
}
