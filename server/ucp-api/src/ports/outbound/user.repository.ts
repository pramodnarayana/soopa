export const USER_REPOSITORY = Symbol('USER_REPOSITORY');

export interface IUserRepository {
  upsertUser(user: { id: string; email?: string; name: string }): Promise<void>;
  upsertTenantUser(tenantUser: {
    tenantId: string;
    userId: string;
    role: string;
  }): Promise<void>;
  removeTenantUser(tenantId: string, userId: string): Promise<void>;
  findUsersByTenant(tenantId: string): Promise<
    {
      id: string;
      email: string;
      name: string;
      role: string;
      createdAt: Date;
    }[]
  >;
}
